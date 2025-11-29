"""
day8_agent.py — Whisperwood Agent (fixed main-thread plugin setup)
"""

import os
import sys
import json
import uuid
import logging
import threading
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional, Annotated
from datetime import datetime

# -----------------------------
# Environment / Thread Limits
# -----------------------------
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
os.environ.setdefault("NUMEXPR_NUM_THREADS", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
os.environ.setdefault("TOKENIZERS_NO_PARALLELISM", "true")
os.environ.setdefault("XLA_PYTHON_CLIENT_PREALLOCATE", "false")

from dotenv import load_dotenv
load_dotenv(".env.local")

# -----------------------------
# LIVEKIT MAIN-THREAD PLUGIN REGISTRATION
# -----------------------------

try:
    from livekit.agents.plugin import Plugin
    if threading.current_thread() is threading.main_thread():

        # Google plugin
        try:
            from livekit.plugins.google import GooglePlugin   # may not exist in all versions
            Plugin.register_plugin(GooglePlugin())
            print("✔ GooglePlugin registered on main thread")
        except Exception:
            print("⚠ GooglePlugin not found or failed to register")

        # OpenAI plugin
        try:
            from livekit.plugins.openai import OpenAIPlugin   # may not exist in all versions
            Plugin.register_plugin(OpenAIPlugin())
            print("✔ OpenAIPlugin registered on main thread")
        except Exception:
            print("⚠ OpenAIPlugin not found or failed to register")

except Exception as e:
    print("⚠ Could not register plugins on main thread:", e)

# --- Standard imports (safe after env setup) ---
from pydantic import Field
from livekit.agents import (
    Agent,
    AgentSession,
    RunContext,
    JobContext,
    JobProcess,
    RoomInputOptions,
    WorkerOptions,
    cli,
    function_tool,
)

# Lightweight plugin imports (these are typically fine)
from livekit.plugins import murf, deepgram, silero, noise_cancellation
from livekit.plugins.turn_detector.multilingual import MultilingualModel

# Logging
logger = logging.getLogger("whisperwood_agent")
logger.setLevel(logging.INFO)
h = logging.StreamHandler(sys.stdout)
h.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
logger.addHandler(h)

# State file
STATE_FILE = Path("whisperwood_state.json")

# -------------------------
# WHISPERWOOD WORLD (your theme)
# -------------------------
WORLD = {
    "intro": {
        "title": "The Whispering Edge of the Forest",
        "desc": (
            "Soft moonlight filters through towering ancient trees. Their branches hum with faint whispers—"
            "as if the forest itself is alive and listening. Fireflies drift around you in gentle spirals, "
            "lighting a narrow path leading deeper into the Grove of Echoes. "
            "A faint silver glow pulses between the roots of an old oak in front of you."
        ),
        "choices": {
            "approach_oak": {
                "desc": "Approach the ancient oak with the silver glow.",
                "result_scene": "oak",
            },
            "follow_path": {
                "desc": "Follow the winding path deeper into Whisperwood.",
                "result_scene": "path",
            },
            "listen_forest": {
                "desc": "Stand still and listen to the whispers in the air.",
                "result_scene": "whispers",
            },
        },
    },

    "oak": {
        "title": "The Heartroot Oak",
        "desc": (
            "You step toward the oak. Silver light pulses from between its roots. "
            "Inside the hollow, you see a small wooden amulet etched with runes. "
            "A soft voice murmurs: 'Choose with care… for the forest remembers.'"
        ),
        "choices": {
            "take_amulet": {
                "desc": "Take the glowing amulet.",
                "result_scene": "amulet_taken",
                "effects": {
                    "add_inventory": "Heartroot Amulet",
                    "add_journal": "You claimed the Heartroot Amulet from the ancient oak."
                }
            },
            "leave_amulet": {
                "desc": "Leave the amulet untouched.",
                "result_scene": "intro",
            },
        },
    },

    "path": {
        "title": "Moonlit Path",
        "desc": (
            "The path glows faintly under the moon. The wind moves strangely, "
            "carrying a soft melody from somewhere ahead. "
            "You spot a stone arch covered in ivy. Beyond it lies darker, denser woods."
        ),
        "choices": {
            "enter_arch": {
                "desc": "Step through the ivy-covered arch.",
                "result_scene": "arch",
            },
            "return_start": {
                "desc": "Go back to the starting clearing.",
                "result_scene": "intro",
            },
        },
    },

    "whispers": {
        "title": "Forest Whispers",
        "desc": (
            "You close your eyes. The forest hum grows louder. Words form: "
            "'A guardian waits… bound by old magic… awakened by choice.' "
            "A warm breeze circles you, as if guiding you somewhere."
        ),
        "choices": {
            "follow_breeze": {
                "desc": "Follow the warm breeze.",
                "result_scene": "arch",
            },
            "ignore": {
                "desc": "Ignore the whispers and stay put.",
                "result_scene": "intro",
            },
        },
    },

    "amulet_taken": {
        "title": "The Amulet's Call",
        "desc": (
            "The moment you lift the amulet, a spark of golden light shoots upward. "
            "The ground trembles. A deer-shaped guardian spirit materializes—formed of leaves and stardust. "
            "Its eyes glow softly as it watches you."
        ),
        "choices": {
            "speak_spirit": {
                "desc": "Speak to the guardian spirit.",
                "result_scene": "spirit",
            },
            "step_back": {
                "desc": "Step back silently.",
                "result_scene": "intro",
            },
        },
    },

    "arch": {
        "title": "The Echo Archway",
        "desc": (
            "Stepping through the arch, the air becomes colder. "
            "Lantern-like mushrooms illuminate a stone pedestal ahead. "
            "On the pedestal rests a crystalline feather humming with energy."
        ),
        "choices": {
            "take_feather": {
                "desc": "Take the crystalline feather.",
                "result_scene": "feather",
                "effects": {
                    "add_inventory": "Crystalline Feather",
                    "add_journal": "Collected a Feather of Echoes from the Archway."
                }
            },
            "leave_feather": {
                "desc": "Leave it and return outside.",
                "result_scene": "intro",
            },
        },
    },

    "spirit": {
        "title": "Guardian of Whisperwood",
        "desc": (
            "The spirit tilts its head. Its voice sounds like rustling leaves: "
            "'Bearer of the Heartroot… will you restore what was stolen? The forest fades without its Echo Flame.'"
        ),
        "choices": {
            "accept_quest": {
                "desc": "Accept the spirit's request.",
                "result_scene": "reward",
                "effects": {
                    "add_journal": "Accepted the quest to restore the Echo Flame."
                }
            },
            "decline": {
                "desc": "Decline the request.",
                "result_scene": "intro",
            }
        },
    },

    "feather": {
        "title": "Feather of Echoes",
        "desc": (
            "The feather pulses with soft resonance. Echoes swirl around you, showing visions of "
            "the forest burning and then healing. The Guardian Spirit appears once more, silent, waiting."
        ),
        "choices": {
            "give_feather": {
                "desc": "Offer the feather to the spirit.",
                "result_scene": "reward",
                "effects": {
                    "add_journal": "Returned the Feather of Echoes.",
                }
            },
            "keep_feather": {
                "desc": "Keep the feather and walk away.",
                "result_scene": "intro",
            },
        },
    },

    "reward": {
        "title": "Restoration of the Echo Flame",
        "desc": (
            "A warm burst of golden light spreads across Whisperwood. "
            "The trees glow gently, their whispers turning into a peaceful hum. "
            "The guardian spirit bows: 'The forest remembers your kindness.'"
        ),
        "choices": {
            "end_session": {
                "desc": "End this chapter of your journey.",
                "result_scene": "intro",
            },
            "continue": {
                "desc": "Keep exploring Whisperwood.",
                "result_scene": "intro",
            },
        },
    },
}

# -------------------------
# Per-session Userdata
# -------------------------
@dataclass
class Userdata:
    player_name: Optional[str] = None
    current_scene: str = "intro"
    history: List[Dict] = field(default_factory=list)
    journal: List[str] = field(default_factory=list)
    inventory: List[str] = field(default_factory=list)
    choices_made: List[str] = field(default_factory=list)
    session_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    started_at: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")


# -------------------------
# JSON SAVE HELPER
# -------------------------
def save_state_to_json(userdata: Userdata):
    scene_key = userdata.current_scene or "intro"
    scene = WORLD.get(scene_key, {})
    state = {
        "session": asdict(userdata),
        "current_scene": {
            "key": scene_key,
            "title": scene.get("title"),
            "description": scene.get("desc"),
            "choices": scene.get("choices"),
        },
        "journal": userdata.journal,
        "inventory": userdata.inventory,
        "history": userdata.history,
        "last_updated_at": datetime.utcnow().isoformat() + "Z",
    }
    try:
        STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")
        logger.debug(f"State saved to {STATE_FILE.resolve()}")
    except Exception as e:
        logger.warning(f"Failed to save state to JSON: {e}")


# -------------------------
# Helper functions
# -------------------------
def scene_text(scene_key: str, userdata: Userdata) -> str:
    scene = WORLD.get(scene_key)
    if not scene:
        return "You are surrounded by silent trees and fog. What do you do?"

    desc = f"{scene['desc']}\n\nChoices:\n"
    for cid, cmeta in scene.get("choices", {}).items():
        desc += f"- {cmeta['desc']} (say: {cid})\n"
    desc += "\nWhat do you do?"
    return desc


def apply_effects(effects: dict, userdata: Userdata):
    if not effects:
        return
    if "add_journal" in effects:
        userdata.journal.append(effects["add_journal"])
    if "add_inventory" in effects:
        userdata.inventory.append(effects["add_inventory"])


def summarize_scene_transition(old_scene: str, action_key: str, result_scene: str, userdata: Userdata) -> str:
    entry = {
        "from": old_scene,
        "action": action_key,
        "to": result_scene,
        "time": datetime.utcnow().isoformat() + "Z",
    }
    userdata.history.append(entry)
    userdata.choices_made.append(action_key)
    return f"You chose '{action_key}'."


# -------------------------
# Agent Tools (function_tool)
# -------------------------
@function_tool
async def start_adventure(
    ctx: RunContext[Userdata],
    player_name: Annotated[Optional[str], Field(description="Player name", default=None)] = None,
) -> str:
    userdata = ctx.userdata
    if player_name:
        userdata.player_name = player_name
    userdata.current_scene = "intro"
    userdata.history = []
    userdata.journal = []
    userdata.inventory = []
    userdata.named_npcs = {} if not hasattr(userdata, "named_npcs") else userdata.named_npcs
    userdata.choices_made = []
    userdata.session_id = str(uuid.uuid4())[:8]
    userdata.started_at = datetime.utcnow().isoformat() + "Z"

    save_state_to_json(userdata)

    opening = (
        f"Greetings {userdata.player_name or 'traveler'}. "
        f"Welcome to '{WORLD['intro']['title']}', a small tale within Whisperwood.\n\n"
        + scene_text("intro", userdata)
    )
    if not opening.endswith("What do you do?"):
        opening += "\nWhat do you do?"
    return opening


@function_tool
async def get_scene(ctx: RunContext[Userdata]) -> str:
    userdata = ctx.userdata
    save_state_to_json(userdata)
    return scene_text(userdata.current_scene or "intro", userdata)


@function_tool
async def player_action(
    ctx: RunContext[Userdata],
    action: Annotated[str, Field(description="Player spoken action or the short action code (e.g., 'approach_oak' or 'take the amulet')")],
) -> str:
    userdata = ctx.userdata
    current = userdata.current_scene or "intro"
    scene = WORLD.get(current)
    action_text = (action or "").strip().lower()

    # Resolve a chosen key
    chosen_key = None
    if action_text in (scene.get("choices") or {}):
        chosen_key = action_text

    if not chosen_key:
        for cid, cmeta in (scene.get("choices") or {}).items():
            desc = cmeta.get("desc", "").lower()
            if cid in action_text or any(w in action_text for w in desc.split()[:4]):
                chosen_key = cid
                break

    if not chosen_key:
        for cid, cmeta in (scene.get("choices") or {}).items():
            for keyword in cmeta.get("desc", "").lower().split():
                if keyword and keyword in action_text:
                    chosen_key = cid
                    break
            if chosen_key:
                break

    if not chosen_key:
        resp = (
            "I didn't quite catch that action in Whisperwood. "
            "Try one of the listed choices, or say a simple phrase like 'approach the oak', 'follow the path', or 'listen to the forest'.\n\n"
            + scene_text(current, userdata)
        )
        return resp

    choice_meta = scene["choices"].get(chosen_key)
    result_scene = choice_meta.get("result_scene", current)
    effects = choice_meta.get("effects", None)

    apply_effects(effects or {}, userdata)
    _note = summarize_scene_transition(current, chosen_key, result_scene, userdata)
    userdata.current_scene = result_scene

    save_state_to_json(userdata)

    next_desc = scene_text(result_scene, userdata)
    persona_pre = "Astraea whispers in a soft, calm voice:\n\n"
    reply = f"{persona_pre}{_note}\n\n{next_desc}"
    if not reply.endswith("What do you do?"):
        reply += "\nWhat do you do?"
    return reply


@function_tool
async def show_journal(ctx: RunContext[Userdata]) -> str:
    userdata = ctx.userdata
    lines = []
    lines.append(f"Session: {userdata.session_id} | Started at: {userdata.started_at}")
    if userdata.player_name:
        lines.append(f"Player: {userdata.player_name}")
    if userdata.journal:
        lines.append("\nJournal entries:")
        for j in userdata.journal:
            lines.append(f"- {j}")
    else:
        lines.append("\nJournal is empty.")
    if userdata.inventory:
        lines.append("\nInventory:")
        for it in userdata.inventory:
            lines.append(f"- {it}")
    else:
        lines.append("\nNo items in inventory.")
    lines.append("\nRecent choices:")
    for h in userdata.history[-6:]:
        lines.append(f"- {h['time']} | from {h['from']} -> {h['to']} via {h['action']}")
    lines.append("\nWhat do you do?")

    save_state_to_json(userdata)
    return "\n".join(lines)


@function_tool
async def restart_adventure(ctx: RunContext[Userdata]) -> str:
    userdata = ctx.userdata
    userdata.current_scene = "intro"
    userdata.history = []
    userdata.journal = []
    userdata.inventory = []
    userdata.choices_made = []
    userdata.session_id = str(uuid.uuid4())[:8]
    userdata.started_at = datetime.utcnow().isoformat() + "Z"

    save_state_to_json(userdata)

    greeting = (
        "The forest hushes and time folds. You return to the clearing as dawn approaches.\n\n"
        + scene_text("intro", userdata)
    )
    if not greeting.endswith("What do you do?"):
        greeting += "\nWhat do you do?"
    return greeting


# -------------------------
# Agent (Astraea Whisperwood)
# -------------------------
class WhisperwoodAgent(Agent):
    def __init__(self):
        instructions = """
        You are Astraea Whisperwood, a mystical, soft-spoken Game Master of an enchanted forest.
        ALWAYS end with "What do you do?".
        Use the tools: start_adventure, get_scene, player_action, show_journal, restart_adventure.
        Keep responses clear, warm, magical, and short enough for spoken TTS.
        """
        super().__init__(
            instructions=instructions,
            tools=[start_adventure, get_scene, player_action, show_journal, restart_adventure],
        )


# -------------------------
# Entrypoint & Prewarm
# -------------------------
def prewarm(proc: JobProcess):
    try:
        proc.userdata["vad"] = silero.VAD.load()
    except Exception:
        logger.warning("VAD prewarm failed; continuing without preloaded VAD.")


async def entrypoint(ctx: JobContext):
    ctx.log_context_fields = {"room": ctx.room.name}
    logger.info("🌲 Starting Whisperwood Fantasy Agent (entrypoint)")

    userdata = Userdata()

    # Extra safety thread caps (again inside process)
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    os.environ.setdefault("OMP_NUM_THREADS", "1")
    os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
    try:
        import torch

        torch.set_num_threads(1)
        torch.set_num_interop_threads(1)
    except Exception:
        pass

    # Attempt to use Google Gemini (lazy import). If loading the plugin at runtime raises plugin registration
    # errors or memory errors, fall back to OpenAI LLM.
    llm_instance = None
    used_gemini = False

    try:
        # Try to import the google plugin (lazy)
        from livekit.plugins import google as livekit_google  # type: ignore

        try:
            # instantiate google LLM
            llm_instance = livekit_google.LLM(model="gemini-2.5-flash")
            used_gemini = True
            logger.info("Using Google Gemini (gemini-2.5-flash) via livekit.plugins.google.")
        except Exception as e:
            logger.warning(f"Failed to instantiate google.LLM(gemini-2.5-flash): {e}")
            llm_instance = None
    except Exception as e:
        logger.warning(f"Could not import livekit.plugins.google (Gemini). Error: {e}")
        llm_instance = None

    # If google not available/failed, fallback to openai if plugin exists
    if llm_instance is None:
        try:
            from livekit.plugins import openai as livekit_openai  # type: ignore
            # default fallback model; you can change via env FALLBACK_OPENAI_MODEL
            fallback_model = os.getenv("FALLBACK_OPENAI_MODEL", "gpt-4o-mini")
            llm_instance = livekit_openai.LLM(model=fallback_model)
            logger.info(f"Falling back to OpenAI LLM ({fallback_model}).")
        except Exception as e:
            logger.error("Failed to initialize an LLM (google or openai). Aborting startup. Error: %s", e)
            raise

    # Build session
    session = AgentSession(
        stt=deepgram.STT(model="nova-3"),
        llm=llm_instance,
        tts=murf.TTS(
            voice=os.getenv("MURF_VOICE", "en-US-alicia"),
            style="Conversational",
            text_pacing=True,
        ),
        turn_detection=MultilingualModel(),
        vad=ctx.proc.userdata.get("vad"),
        userdata=userdata,
    )

    # Start agent
    await session.start(
        agent=WhisperwoodAgent(),
        room=ctx.room,
        room_input_options=RoomInputOptions(noise_cancellation=noise_cancellation.BVC()),
    )

    await ctx.connect()


if __name__ == "__main__":
    # prefer main-process mode on Windows to reduce spawn-time plugin issues
    try:
        cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint, prewarm_fnc=prewarm, use_main_process=True))
    except TypeError:
        # older livekit.agents may not accept use_main_process
        cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint, prewarm_fnc=prewarm))
