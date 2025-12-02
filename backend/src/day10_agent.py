"""
Final single-file agent.py for Day 10 — Improv Battle
- Merges state, scenarios and system prompt into one file
- Player name is HARD-FIXED to "Sara" (agent will not ask for name)
- Tools exposed: start_show, next_scenario, record_performance, summarize_show, stop_show
- Uses Deepgram STT, Murf TTS, Google Gemini LLM (gemini-2.5-flash / gemini-2.0-flash adjustable)
- Designed for LiveKit voice worker runtime
"""

import json
import logging
import os
import uuid
import random
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Optional, Annotated

from dotenv import load_dotenv
from pydantic import Field
from livekit.agents import (
    Agent,
    AgentSession,
    JobContext,
    JobProcess,
    RoomInputOptions,
    WorkerOptions,
    cli,
    function_tool,
    RunContext,
)

from livekit.plugins import murf, silero, google, deepgram, noise_cancellation
from livekit.plugins.turn_detector.multilingual import MultilingualModel

# -------------------------
# Logging
# -------------------------
logger = logging.getLogger("improv_battle_agent")
logger.setLevel(logging.INFO)
handler = logging.StreamHandler()
handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
logger.addHandler(handler)

load_dotenv(".env.local")

# -------------------------
# SYSTEM PROMPT (final integrated prompt)
# -------------------------
SYSTEM_PROMPT = """
You are the energetic TV host of a fast-paced voice improv show called "Improv Battle."
Speak like a charismatic, witty, fun game show host. Keep your lines short, punchy, and perfect for TTS.

STRICT RULES:
- The backend controls ALL game logic: rounds, scenarios, reactions, and flow.
- NEVER ask for the player's name. The player's name is always "Sara".
- NEVER ask the player to start the game. Backend triggers all steps.
- NEVER ask for the scenario. Backend gives it.
- NEVER call tools on your own. Only respond inside the tool that is currently running.
- NEVER talk about backend, JSON, code, data messages, or tools.
- NEVER break character.

STYLE:
- High energy, witty, playful, charismatic.
- Light teasing allowed; always respectful and fun.
- No negativity, no insults, no harsh comments.
- Keep lines clean, rhythmic, easy for TTS.
- Project confidence; sound like a real TV host hyping the show.

SCENARIO PRESENTATION:
When backend provides a scenario during present_scenario():
- Start with: "Round X begins!"
- Present scenario in 1–2 sharp lines.
- Encourage: "When you're ready, jump into character and perform!"

IMPROV REACTIONS:
Backend chooses reaction tone (supportive / neutral / mild critique). You only generate the written host reaction based on the category implied by backend’s instruction.
Your reaction should:
- Be 2–4 sentences.
- Reference specific player words or choices the backend passes.
- Feel spontaneous, sharp, and TV-host-like.
- Add charm, a bit of humor, and personality.
- Keep mild critique constructive and friendly.

ENDING THE SHOW:
When backend calls summarize_show() or the final round ends:
- Summarize Sara's improv style in 1–2 lines.
- Highlight 1–3 memorable lines or choices referenced by backend.
- Thank Sara warmly and sign off like a TV host.

EARLY EXIT:
If player wants to stop, keep replies brief and polite. Backend will finalize shutdown.

CONTENT SAFETY:
- No violence, sexuality, hate, or harmful content.
- If user says something unsafe, gently redirect back to creativity.

GOAL:
Be fast, fun, witty, charming — the perfect host guiding each improv round with style.
"""

# -------------------------
# SCENARIOS (merged from scenarios.json)
# -------------------------
SCENARIOS = [
    "You are a barista who must tell a customer that their latte is a portal to another dimension.",
    "You are a time-travelling tour guide explaining modern smartphones to someone from the 1800s.",
    "You are a waiter who must calmly tell a customer that their order has escaped the kitchen.",
    "You are a customer returning an obviously cursed object to a skeptical shop owner.",
    "You are a street food vendor describing your famous golgappa recipe to a curious customer.",
    "You are an astronaut arguing with a plant about whether it deserves to go to Mars.",
    "You are an HR manager firing someone for turning office chairs into tiny boats.",
    "You are a wedding planner explaining a chaotic wedding entrance.",
    "You are an auto-rickshaw driver explaining a dramatic scenic shortcut to a nervous tourist.",
    "You are a librarian explaining why books in your library rearrange themselves by mood.",
    "You are a baker who accidentally baked a cake that makes people confess secrets.",
    "You are a museum guide trying to explain why an ancient statue is cracking jokes.",
    "You are a customer service agent helping someone place a massive rice order.",
    "You are a detective realizing that every clue is actually a musical instrument.",
    "You are a haunted hotel concierge trying to upsell 'friendly ghost experiences'."
]

# -------------------------
# Per-session state (merged from state.py)
# -------------------------
class GamePhase:
    INTRO = "intro"
    AWAITING_IMPROV = "awaiting_improv"
    REACTING = "reacting"
    DONE = "done"


@dataclass
class ImprovisationState:
    player_name: str = "Sara"  # FIXED NAME
    current_round: int = 0
    max_rounds: int = 3
    rounds: List[Dict] = field(default_factory=list)
    phase: str = GamePhase.INTRO
    current_scenario: Optional[str] = None
    scenarios: List[str] = field(default_factory=lambda: SCENARIOS.copy())

    END_PHRASES = {
        "end scene", "end", "done", "that's it", "finished",
        "ok i'm done", "i'm done",
        "next", "move on", "go to round",
        "go to round two", "go to round three",
        "stop the game", "stop game", "stop session", "end session",
        "end the session", "exit", "exit game", "exit the game",
        "end show", "end the show"
    }

    # Reset for a new game
    def reset_for_new_game(self, max_rounds: int = None):
        self.current_round = 0
        self.rounds = []
        self.phase = GamePhase.INTRO
        self.current_scenario = None
        if max_rounds is not None:
            self.max_rounds = max_rounds

    def pick_next_scenario(self) -> str:
        # pick by index cycling through list for deterministic order (but could randomize)
        if not self.scenarios:
            self.scenarios = SCENARIOS.copy()
        idx = (self.current_round) % len(self.scenarios)
        self.current_scenario = self.scenarios[idx]
        return self.current_scenario

    def start_round(self) -> str:
        self.current_round += 1
        scenario = self.pick_next_scenario()
        self.rounds.append({
            "round": self.current_round,
            "scenario": scenario,
            "player_turns": [],
            "host_reaction": None
        })
        self.phase = GamePhase.AWAITING_IMPROV
        return scenario

    def add_player_turn(self, transcript: str):
        if not self.rounds:
            self.start_round()
        self.rounds[-1]["player_turns"].append(transcript)

    def finish_round(self, reaction_text: str):
        if self.rounds:
            self.rounds[-1]["host_reaction"] = reaction_text
        if self.current_round >= self.max_rounds:
            self.phase = GamePhase.DONE
        else:
            self.phase = GamePhase.AWAITING_IMPROV

    def is_done(self) -> bool:
        return self.phase == GamePhase.DONE

    def looks_like_scene_end(self, transcript: str) -> bool:
        txt = (transcript or "").lower().strip()
        for phrase in self.END_PHRASES:
            if phrase in txt:
                return True
        if len(txt.split()) <= 2 and txt in {"ok", "okay", "yes"}:
            return False
        if "ready for" in txt or "next round" in txt:
            return True
        return False

    def summary(self) -> str:
        if not self.rounds:
            return "You didn’t get to perform any rounds."
        highlight_lines = []
        for r in self.rounds:
            turns = " ".join(r.get("player_turns", []))
            if turns:
                snippet = turns[:80] + ("..." if len(turns) > 80 else "")
                highlight_lines.append(f"Round {r['round']}: {snippet}")
        persona = "an imaginative improviser"
        all_turns = " ".join(" ".join(r["player_turns"]) for r in self.rounds).lower()
        if "emotion" in all_turns:
            persona = "an emotionally expressive performer"
        if "character" in all_turns:
            persona = "a strong character improviser"
        return f"You seemed like {persona}. Here are some highlights:\n" + "\n".join(highlight_lines[:3])

# -------------------------
# Small helpers: scenario picker + reaction heuristics
# -------------------------
def _pick_random_scenario(state: ImprovisationState) -> str:
    # prefer cycling, but allow randomness if desired
    return state.start_round()

def _host_reaction_text(performance: str) -> str:
    # Lightweight heuristic to vary reaction tone and pick highlight
    performance_lower = (performance or "").lower()
    tones = ["supportive", "neutral", "mildly_critical"]
    tone = random.choice(tones)
    highlights = []
    if any(w in performance_lower for w in ("funny", "haha", "lol")):
        highlights.append("great comedic timing")
    if any(w in performance_lower for w in ("sad", "cry", "tears")):
        highlights.append("good emotional depth")
    if any(w in performance_lower for w in ("pause", "...")):
        highlights.append("interesting use of silence")
    if not highlights:
        highlights.append(random.choice(["nice character choices", "bold energy", "unexpected twist"]))
    chosen = random.choice(highlights)
    if tone == "supportive":
        return f"Loved that — {chosen}! Very vivid. Nice work."
    elif tone == "neutral":
        return f"Hmm — {chosen}. Some parts landed, some were light. Keep exploring."
    else:
        return f"Okay — {chosen}, but pacing felt a bit rushed. Push the choices more next round."

# -------------------------
# Tools: start_show, next_scenario, record_performance, summarize_show, stop_show
# -------------------------
@function_tool
async def start_show(
    ctx: RunContext,
    name: Annotated[Optional[str], Field(description="IGNORED — name is always Sara", default=None)] = None,
    max_rounds: Annotated[int, Field(description="Number of rounds (3-5 recommended)", default=3)] = 3,
) -> str:
    """
    Initialize the session state and immediately present round 1 scenario.
    Note: name is ignored — Sara is always used.
    """
    # store / create userdata state on ctx.proc.userdata if available, otherwise create local
    # The Agent runtime will attach a userdata object to ctx.proc.userdata; prefer using it if present.
    # For clarity we use a small local state container per run.
    userdata = getattr(ctx, "userdata", None)
    if userdata is None:
        # fallback simple container
        state = ImprovisationState()
    else:
        # if userdata is the ImprovisationState instance, reuse it; else attach new
        if isinstance(userdata, ImprovisationState):
            state = userdata
        else:
            # try if ctx.userdata has attribute 'improv_state' (older flows)
            state = ImprovisationState()
            # if ctx.userdata is a dict-like, try to load values (best-effort)
            try:
                if hasattr(ctx, "userdata") and isinstance(ctx.userdata, dict):
                    d = ctx.userdata
                    if "max_rounds" in d:
                        state.max_rounds = int(d.get("max_rounds", state.max_rounds))
            except Exception:
                pass

    # FORCE name to Sara
    state.player_name = "Sara"
    # sanitize max_rounds
    if max_rounds < 1:
        max_rounds = 1
    if max_rounds > 8:
        max_rounds = 8
    state.max_rounds = int(max_rounds)
    state.reset_for_new_game(max_rounds=state.max_rounds)

    # start first round and present scenario immediately to reduce round-trip
    scenario = state.start_round()
    state.phase = GamePhase.AWAITING_IMPROV

    # attach state back if possible
    if hasattr(ctx, "userdata") and not isinstance(ctx.userdata, ImprovisationState):
        try:
            ctx.userdata = state
        except Exception:
            pass

    intro = (
        f"Welcome to Improv Battle, Sara! We'll play {state.max_rounds} rounds. "
        "Rules: I'll give you a quick scene, you'll improvise in character. "
        "When you're done say 'End scene' or pause — I'll react and move on. Have fun!"
    )

    return intro + f"\n\nRound 1 begins! {scenario}\nWhen you're ready, jump into character and perform!"

@function_tool
async def next_scenario(ctx: RunContext) -> str:
    """
    Advance to the next scenario. If finished, call summarize_show.
    """
    # retrieve state from ctx.userdata if present
    state = getattr(ctx, "userdata", None) or ImprovisationState()
    # if state is not of our type but has improv_state, adapt (best-effort)
    if not isinstance(state, ImprovisationState):
        # attempt to create a new state and keep round count if possible
        state = ImprovisationState()

    if state.is_done():
        state.phase = GamePhase.DONE
        return await summarize_show(ctx)

    if state.current_round >= state.max_rounds:
        state.phase = GamePhase.DONE
        return await summarize_show(ctx)

    # start next round
    scenario = state.start_round()
    state.phase = GamePhase.AWAITING_IMPROV
    return f"Round {state.current_round} begins! {scenario}\nWhen you're ready, jump into character and perform!"

@function_tool
async def record_performance(
    ctx: RunContext,
    performance: Annotated[str, Field(description="Player's improv performance (transcribed text)")],
) -> str:
    """
    Save the player's performance, generate a reaction, and advance state.
    Caller should pass the transcription text (from STT).
    """
    state = getattr(ctx, "userdata", None) or ImprovisationState()
    if not isinstance(state, ImprovisationState):
        state = ImprovisationState()

    # If no round started yet, start one (defensive)
    if state.current_round == 0:
        state.start_round()

    state.add_player_turn(performance)
    reaction = _host_reaction_text(performance)
    state.finish_round(reaction)

    # If final round, produce closing summary after reaction
    if state.current_round >= state.max_rounds or state.is_done():
        state.phase = GamePhase.DONE
        closing = f"{reaction}\n\nThat was the final round, Sara. " + (await summarize_show(ctx))
        return closing

    # otherwise prompt for next round
    return f"{reaction}\n\nRound {state.current_round} complete! When you're ready, say 'Next' or I'll give you the next scene."

@function_tool
async def summarize_show(ctx: RunContext) -> str:
    """
    Provide a closing summary referencing highlights from state.
    """
    state = getattr(ctx, "userdata", None) or ImprovisationState()
    if not isinstance(state, ImprovisationState):
        state = ImprovisationState()

    if not state.rounds:
        return "No rounds were played, Sara. Thanks for stopping by Improv Battle!"

    lines = [f"Thanks for performing, Sara! Here's a short recap:"]

    for r in state.rounds:
        perf = (r.get("player_turns") or [""])[0] if r.get("player_turns") else r.get("performance", "")
        if isinstance(perf, list):
            perf = " ".join(perf)
        perf_snip = perf.strip()
        if len(perf_snip) > 80:
            perf_snip = perf_snip[:77] + "..."
        lines.append(f"Round {r.get('round')}: {r.get('scenario')} — You: '{perf_snip}' | Host: {r.get('host_reaction') or ''}")

    # basic profile heuristic
    mentions_character = sum(1 for r in state.rounds if any(w in " ".join(r.get("player_turns", [])).lower() for w in ("i am", "i'm", "as a", "character", "role")))
    mentions_emotion = sum(1 for r in state.rounds if any(w in " ".join(r.get("player_turns", [])).lower() for w in ("sad", "angry", "happy", "love", "cry", "tears")))

    profile = "You seemed playful and adventurous."
    if mentions_character > len(state.rounds) / 2:
        profile = "You commit to character choices — strong work!"
    elif mentions_emotion > 0:
        profile = "You bring emotional color to scenes."

    lines.append(profile + " Keep leaning into clear choices, Sara!")
    return "\n".join(lines)

@function_tool
async def stop_show(ctx: RunContext, confirm: Annotated[bool, Field(description="Confirm stop", default=False)] = False) -> str:
    """
    Graceful early exit. If confirm is False, ask the user to confirm.
    """
    if not confirm:
        return "Are you sure you want to stop the show, Sara? Say 'stop show yes' to confirm."
    # on confirm, mark done
    state = getattr(ctx, "userdata", None) or ImprovisationState()
    state.phase = GamePhase.DONE
    return "Show stopped. Thanks for performing today, Sara!"

# -------------------------
# The Agent (Improv Host)
# -------------------------
class GameMasterAgent(Agent):
    def __init__(self):
        # Instructions are strict and TTS-friendly
        instructions = SYSTEM_PROMPT + "\n\nPlayer name: Sara (fixed)."
        super().__init__(instructions=instructions, tools=[start_show, next_scenario, record_performance, summarize_show, stop_show])

# -------------------------
# Entrypoint & Prewarm
# -------------------------
def prewarm(proc: JobProcess):
    # load VAD model if available
    try:
        proc.userdata["vad"] = silero.VAD.load()
    except Exception:
        logger.warning("VAD prewarm failed; continuing without preloaded VAD.")

async def entrypoint(ctx: JobContext):
    ctx.log_context_fields = {"room": ctx.room.name}
    logger.info("🚀 STARTING Improv Battle voice host")

    # Create per-session state container and attach to session via userdata
    session_state = ImprovisationState()
    session_state.player_name = "Sara"

    session = AgentSession(
        stt=deepgram.STT(model="nova-3"),
        llm=google.LLM(model=os.getenv("LLM_MODEL", "gemini-2.5-flash")),
        tts=murf.TTS(
            voice=os.getenv("MURF_VOICE", "en-IN-anusha"),
            style="Conversation",
        ),
        turn_detection=MultilingualModel(),
        vad=ctx.proc.userdata.get("vad"),
        userdata=session_state,
    )

    usage = None
    try:
        usage = session.usage_collector = getattr(session, "usage_collector", None)
    except Exception:
        usage = None

    await session.start(
        agent=GameMasterAgent(),
        room=ctx.room,
        room_input_options=RoomInputOptions(noise_cancellation=noise_cancellation.BVC()),
    )

    await ctx.connect()

if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint, prewarm_fnc=prewarm))
