import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Annotated
from datetime import datetime

from dotenv import load_dotenv
from pydantic import Field

from livekit.agents import (
    Agent, AgentSession, JobContext, JobProcess,
    RoomInputOptions, WorkerOptions, cli,
    function_tool, RunContext,
    metrics, MetricsCollectedEvent,
)

from livekit.plugins import murf, silero, google, deepgram, noise_cancellation
from livekit.plugins.turn_detector.multilingual import MultilingualModel

from commerce.merchant import (
    list_products as merchant_list_products,
    create_order as merchant_create_order,
    get_last_order as merchant_get_last_order
)

load_dotenv(".env.local")
logger = logging.getLogger("day9_agent")


# ---------------------------------------------------
# SESSION DATA
# ---------------------------------------------------
@dataclass
class EcommerceSessionData:
    last_shown: List[Dict] = field(default_factory=list)
    last_order: Optional[Dict] = None
    buyer: Dict = field(default_factory=dict)


# ---------------------------------------------------
# FUNCTION TOOLS
# ---------------------------------------------------
@function_tool
async def list_products_tool(
    ctx: RunContext[EcommerceSessionData],
    category: Annotated[Optional[str], Field(default=None, description="Category filter")] = None,
    color: Annotated[Optional[str], Field(default=None, description="Color filter")] = None,
    max_price: Annotated[Optional[float], Field(default=None, description="Max price filter")] = None,
    q: Annotated[Optional[str], Field(default=None, description="Keyword search")] = None,
) -> Dict[str, Any]:

    filters = {}
    if category: filters["category"] = category
    if color: filters["color"] = color
    if max_price is not None: filters["max_price"] = max_price
    if q: filters["q"] = q.strip()

    products = merchant_list_products(filters=filters, limit=8)
    ctx.userdata.last_shown = products
    return {"products": products, "count": len(products), "filters": filters}


@function_tool
async def create_order_tool(
    ctx: RunContext[EcommerceSessionData],
    line_items: Annotated[List[Dict], Field(description="List of line items")] = None,
    buyer_name: Annotated[Optional[str], Field(default=None, description="Buyer name")] = None,
    buyer_email: Annotated[Optional[str], Field(default=None, description="Buyer email")] = None,
) -> Dict[str, Any]:

    buyer = {}
    if buyer_name:
        buyer["name"] = buyer_name
    if buyer_email:
        buyer["email"] = buyer_email

    order = merchant_create_order(
        line_items=line_items,
        buyer=buyer
    )
    ctx.userdata.last_order = order
    return {"order": order}


@function_tool
async def get_last_order_tool(
    ctx: RunContext[EcommerceSessionData],
) -> Dict[str, Any]:
    return {"last_order": merchant_get_last_order()}


# ---------------------------------------------------
# AGENT
# ---------------------------------------------------
class EcommerceAgent(Agent):
    def __init__(self):
        super().__init__(
instructions="""
You are a friendly, professional voice shopping assistant.

YOUR CORE LOGIC:
1. NEVER call a tool with empty arguments.
2. If the user has not specified what item they want:
       → DO NOT call list_products_tool.
       → Ask: “Sure! What kind of product are you looking for?”
3. ONLY call list_products_tool when the user expresses a search intent like:
       “show me hoodies”
       “mugs under 500”
       “black t-shirts”
4. Extract only what the user said (category, color, price, keyword).
5. Unknown details = None.
6. If list_products_tool returns multiple results:
       → summarize and ask which one they want.
7. For ordering:
       → Use create_order_tool with product_id and quantity.
       → If user says “second one”, choose from last_shown list.
8. To check last order:
       → Use get_last_order_tool().
9. NEVER guess product IDs.
Respond naturally, short, clear, and helpful.
""",
            tools=[list_products_tool, create_order_tool, get_last_order_tool],
        )


# ---------------------------------------------------
# PREWARM
# ---------------------------------------------------
def prewarm(proc: JobProcess):
    proc.userdata["vad"] = silero.VAD.load()


# ---------------------------------------------------
# ENTRYPOINT
# ---------------------------------------------------
async def entrypoint(ctx: JobContext):
    print("\n" + "="*60)
    print("🏬 DAY 9 — E-COMMERCE VOICE AGENT STARTED")
    print("📁 Orders saved in: src/data/orders.json")
    print("="*60 + "\n")

    userdata = EcommerceSessionData()

    session = AgentSession(
        stt=deepgram.STT(model="nova-3"),
        llm=google.LLM(model="gemini-2.5-flash"),
        tts=murf.TTS(
            voice="en-US-matthew",
            style="Conversation",
            text_pacing=True,
        ),
        turn_detection=MultilingualModel(),
        vad=ctx.proc.userdata["vad"],
        userdata=userdata,
    )

    usage = metrics.UsageCollector()

    @session.on("metrics_collected")
    def _(ev: MetricsCollectedEvent):
        usage.collect(ev.metrics)

    await session.start(
        agent=EcommerceAgent(),
        room=ctx.room,
        room_input_options=RoomInputOptions(
            noise_cancellation=noise_cancellation.BVC()
        )
    )

    await ctx.connect()


if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint, prewarm_fnc=prewarm))
