import logging

from dotenv import load_dotenv
from livekit.agents import (
    Agent,
    AgentSession,
    JobContext,
    JobProcess,
    MetricsCollectedEvent,
    RoomInputOptions,
    WorkerOptions,
    cli,
    metrics,
    tokenize,
    # function_tool,
    # RunContext
)
from livekit.plugins import murf, silero, google, deepgram, noise_cancellation
from livekit.plugins.turn_detector.multilingual import MultilingualModel

logger = logging.getLogger("agent")

load_dotenv(".env.local")

import json
import os
os.makedirs("orders", exist_ok=True)

async def save_order(order):
    folder = "orders"
    filepath = os.path.join(folder, f"order_{order['name']}.json")
    with open(filepath, "w") as f:
        json.dump(order, f, indent=2)
    print("Order saved to", filepath)



class Assistant(Agent):
    def __init__(self) -> None:
        super().__init__(
             instructions="""You are a friendly barista working at Gaza Coffee.
                Your job is to take coffee orders through a natural voice conversation.

                Always follow these rules:
                1. Ask questions one by one until the order is complete.
                2. Maintain and update an order object with fields:
                - drinkType
                - size
                - milk
                - extras
                - name
                3. After confirming all details, say the final order summary out loud,
                then tell the user that you are saving their order.
                4. Do NOT provide random info; stay in character as a barista.
                5. Keep responses short and friendly.""",
     )

    # To add tools, use the @function_tool decorator.
    # Here's an example that adds a simple weather tool.
    # You also have to add `from livekit.agents import function_tool, RunContext` to the top of this file
    # @function_tool
    # async def lookup_weather(self, context: RunContext, location: str):
    #     """Use this tool to look up current weather information in the given location.
    #
    #     If the location is not supported by the weather service, the tool will indicate this. You must tell the user the location's weather is unavailable.
    #
    #     Args:
    #         location: The location to look up weather information for (e.g. city name)
    #     """
    #
    #     logger.info(f"Looking up weather for {location}")
    #
    #     return "sunny with a temperature of 70 degrees."


def prewarm(proc: JobProcess):
    proc.userdata["vad"] = silero.VAD.load()


async def entrypoint(ctx: JobContext):
    # Logging setup
    # Add any other context you want in all log entries here
    ctx.log_context_fields = {
        "room": ctx.room.name,
    }

    # Set up a voice AI pipeline using OpenAI, Cartesia, AssemblyAI, and the LiveKit turn detector
    session = AgentSession(
        # Speech-to-text
        stt=deepgram.STT(model="nova-3"),

        # Language model
        llm=google.LLM(
            model="gemini-2.5-flash",
        ),

        # Text-to-speech
        tts=murf.TTS(
            voice="en-US-matthew",
            style="Conversation",
            tokenizer=tokenize.basic.SentenceTokenizer(min_sentence_len=2),
            text_pacing=True
        ),

        turn_detection=MultilingualModel(),
        vad=ctx.proc.userdata["vad"],
        preemptive_generation=True,
    )

    #  DAY 2: Coffee Order State
    order = {
        "drinkType": None,
        "size": None,
        "milk": None,
        "extras": [],
        "name": None,
    }

    # DAY 2: Handle User Speech Input
    async def handle_user_message(text: str):
        t = text.lower()

        # Extract drink type
        for d in ["latte", "mocha", "espresso", "americano", "cappuccino"]:
            if order["drinkType"] is None and d in t:
                order["drinkType"] = d
                return "Great choice! What size would you like? Small, medium, or large?"

        # Extract size
        for s in ["small", "medium", "large"]:
            if order["size"] is None and s in t:
                order["size"] = s
                return "Got it! What kind of milk would you like? Whole, oat, almond, or soy?"

        # Extract milk type
        for m in ["oat", "almond", "soy", "whole"]:
            if order["milk"] is None and m in t:
                order["milk"] = m
                return "Nice! Any extras? You can say whipped cream, caramel, or extra shot."

        # Extract extras
        for e in ["whipped cream", "caramel", "extra shot", "whipped", "shot"]:
            if e in t:
                order["extras"].append(e)
                return "Added! What's your name for the order?"

        # Extract name (single word)
        if order["name"] is None and len(text.split()) == 1:
            order["name"] = text.capitalize()
            return "Perfect! Let me summarize your order."

        # Final save
        if order["drinkType"] and order["size"] and order["milk"] and order["name"]:
            await save_order(order)

            await session.say(
                f"Thanks {order['name']}! Your {order['size']} {order['drinkType']} with {order['milk']} milk is ready. I have saved your order!"
            )

        return None


    # To use a realtime model instead of a voice pipeline, use the following session setup instead.
    # (Note: This is for the OpenAI Realtime API. For other providers, see https://docs.livekit.io/agents/models/realtime/))
    # 1. Install livekit-agents[openai]
    # 2. Set OPENAI_API_KEY in .env.local
    # 3. Add `from livekit.plugins import openai` to the top of this file
    # 4. Use the following session setup instead of the version above
    # session = AgentSession(
    #     llm=openai.realtime.RealtimeModel(voice="marin")
    # )

    # Metrics collection, to measure pipeline performance
    # For more information, see https://docs.livekit.io/agents/build/metrics/
    usage_collector = metrics.UsageCollector()

    @session.on("metrics_collected")
    def _on_metrics_collected(ev: MetricsCollectedEvent):
        metrics.log_metrics(ev.metrics)
        usage_collector.collect(ev.metrics)

    async def log_usage():
        summary = usage_collector.get_summary()
        logger.info(f"Usage: {summary}")

    ctx.add_shutdown_callback(log_usage)

    # # Add a virtual avatar to the session, if desired
    # # For other providers, see https://docs.livekit.io/agents/models/avatar/
    # avatar = hedra.AvatarSession(
    #   avatar_id="...",  # See https://docs.livekit.io/agents/models/avatar/plugins/hedra
    # )
    # # Start the avatar and wait for it to join
    # await avatar.start(session, room=ctx.room)

    # Start the session, which initializes the voice pipeline and warms up the models
    await session.start(
        agent=Assistant(),
        room=ctx.room,
        room_input_options=RoomInputOptions(
            # For telephony applications, use `BVCTelephony` for best results
            noise_cancellation=noise_cancellation.BVC(),
        ),
    )

     # 1 function that handles + responds
    async def handle_and_respond(text: str):
        reply = await handle_user_message(text)
        if reply:
            await session.say(reply)

    # 2 transcription event listener
    def on_transcription(ev):
        if not ev.text:
            return
        
        import asyncio
        asyncio.create_task(handle_and_respond(ev.text))

    # 3 register event listener
    session.on("transcription", on_transcription)

if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint, prewarm_fnc=prewarm))
