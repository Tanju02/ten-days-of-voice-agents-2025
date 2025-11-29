import sqlite3
import os
import json
from datetime import datetime
from typing import List, Optional, Dict, Any
from dataclasses import dataclass
import threading

# ---------------------------------------------------------
# PATHS
# ---------------------------------------------------------
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# Day 4 (Tutor Agent)
TUTOR_DB_PATH = os.path.join(SCRIPT_DIR, "..", "tutor_state", "mastery.db")

# Day 6 (Fraud Agent)
FRAUD_DB_PATH = os.path.join(SCRIPT_DIR, "fraud_cases.db")

lock = threading.Lock()

# =========================================================
# ⭐ DAY 4 — TUTOR AGENT MASTER DB
# =========================================================

def init_mastery_db():
    """Initialize Day 4 Tutor Master DB."""
    with lock:
        conn = sqlite3.connect(TUTOR_DB_PATH)
        c = conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS mastery (
                concept_id TEXT PRIMARY KEY,
                times_explained INTEGER DEFAULT 0,
                times_quizzed INTEGER DEFAULT 0,
                times_taught_back INTEGER DEFAULT 0,
                last_score INTEGER,
                avg_score REAL
            )
        """)
        conn.commit()
        conn.close()


def save_mastery(concept_id, data):
    """Save mastery progress for tutor agent."""
    with lock:
        conn = sqlite3.connect(TUTOR_DB_PATH)
        c = conn.cursor()
        c.execute("""
            INSERT INTO mastery 
            (concept_id, times_explained, times_quizzed, times_taught_back, last_score, avg_score)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(concept_id) DO UPDATE SET
                times_explained=excluded.times_explained,
                times_quizzed=excluded.times_quizzed,
                times_taught_back=excluded.times_taught_back,
                last_score=excluded.last_score,
                avg_score=excluded.avg_score
        """, (
            concept_id,
            data.get("times_explained", 0),
            data.get("times_quizzed", 0),
            data.get("times_taught_back", 0),
            data.get("last_score"),
            data.get("avg_score")
        ))
        conn.commit()
        conn.close()


def load_mastery():
    """Load tutor mastery table."""
    with lock:
        conn = sqlite3.connect(TUTOR_DB_PATH)
        c = conn.cursor()
        rows = c.execute("SELECT * FROM mastery").fetchall()
        conn.close()

    mastery = {}
    for row in rows:
        mastery[row[0]] = {
            "times_explained": row[1],
            "times_quizzed": row[2],
            "times_taught_back": row[3],
            "last_score": row[4],
            "avg_score": row[5],
        }
    return mastery


# =========================================================
# ⭐ DAY 6 — FRAUD AGENT DB
# =========================================================

@dataclass
class FraudCase:
    id: str
    userName: str
    securityIdentifier: str
    cardEnding: str
    cardType: str
    transactionName: str
    transactionAmount: str
    transactionTime: str
    transactionLocation: str
    transactionCategory: str
    transactionSource: str
    status: str
    securityQuestion: str
    securityAnswer: str
    createdAt: str
    outcome: str = "pending"
    outcomeNote: str = ""


class FraudDatabase:
    def __init__(self, db_path: str = FRAUD_DB_PATH):
        self.db_path = db_path
        self.init_database()

    # ------------------------------
    # CREATE FRAUD TABLE
    # ------------------------------
    def init_database(self):
        """Initialize fraud case table."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS fraud_cases (
                id TEXT PRIMARY KEY,
                userName TEXT NOT NULL,
                securityIdentifier TEXT,
                cardEnding TEXT NOT NULL,
                cardType TEXT,
                transactionName TEXT,
                transactionAmount TEXT,
                transactionTime TEXT,
                transactionLocation TEXT,
                transactionCategory TEXT,
                transactionSource TEXT,
                status TEXT DEFAULT 'pending',
                securityQuestion TEXT,
                securityAnswer TEXT,
                outcome TEXT DEFAULT 'pending',
                outcomeNote TEXT,
                createdAt TEXT,
                lastUpdated TEXT
            )
        """)

        conn.commit()
        conn.close()

    # ------------------------------
    # INSERT NEW CASE
    # ------------------------------
    def add_fraud_case(self, case: FraudCase) -> bool:
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute("""
                INSERT INTO fraud_cases (
                    id, userName, securityIdentifier, cardEnding, cardType,
                    transactionName, transactionAmount, transactionTime,
                    transactionLocation, transactionCategory, transactionSource,
                    status, securityQuestion, securityAnswer, outcome,
                    outcomeNote, createdAt, lastUpdated
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                case.id, case.userName, case.securityIdentifier, case.cardEnding,
                case.cardType, case.transactionName, case.transactionAmount,
                case.transactionTime, case.transactionLocation, case.transactionCategory,
                case.transactionSource, case.status, case.securityQuestion,
                case.securityAnswer, case.outcome, case.outcomeNote,
                case.createdAt, datetime.now().isoformat()
            ))

            conn.commit()
            conn.close()
            return True

        except Exception as e:
            print("Error adding fraud case:", e)
            return False

    # ------------------------------
    # FETCH ALL CASES
    # ------------------------------
    def get_all_fraud_cases(self) -> List[FraudCase]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM fraud_cases")
        rows = cursor.fetchall()
        conn.close()

        return [self._row_to_case(r) for r in rows]

    # ------------------------------
    # FETCH CASE BY LAST 4 DIGITS
    # ------------------------------
    def get_fraud_case_by_card(self, card_ending: str) -> Optional[FraudCase]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM fraud_cases WHERE cardEnding = ?", (card_ending,))
        row = cursor.fetchone()
        conn.close()

        return self._row_to_case(row) if row else None

    # ------------------------------
    # UPDATE STATUS
    # ------------------------------
    def update_fraud_case_status(self, case_id: str, status: str, outcome: str, note: str) -> bool:
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute("""
                UPDATE fraud_cases
                SET status = ?, outcome = ?, outcomeNote = ?, lastUpdated = ?
                WHERE id = ?
            """, (
                status, outcome, note,
                datetime.now().isoformat(),
                case_id
            ))

            conn.commit()
            conn.close()
            return True

        except Exception as e:
            print("Error updating status:", e)
            return False

    # ------------------------------
    # STATS
    # ------------------------------
    def get_statistics(self) -> Dict[str, Any]:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(*) FROM fraud_cases")
        total = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM fraud_cases WHERE status = 'confirmed_fraud'")
        fraud = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM fraud_cases WHERE status = 'confirmed_safe'")
        safe = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM fraud_cases WHERE status = 'pending'")
        pending = cursor.fetchone()[0]

        conn.close()

        return {
            "total_cases": total,
            "confirmed_fraud": fraud,
            "confirmed_safe": safe,
            "pending": pending,
        }

    # ------------------------------
    # ROW → OBJECT
    # ------------------------------
    def _row_to_case(self, row):
        return FraudCase(
            id=row["id"],
            userName=row["userName"],
            securityIdentifier=row["securityIdentifier"],
            cardEnding=row["cardEnding"],
            cardType=row["cardType"],
            transactionName=row["transactionName"],
            transactionAmount=row["transactionAmount"],
            transactionTime=row["transactionTime"],
            transactionLocation=row["transactionLocation"],
            transactionCategory=row["transactionCategory"],
            transactionSource=row["transactionSource"],
            status=row["status"],
            securityQuestion=row["securityQuestion"],
            securityAnswer=row["securityAnswer"],
            outcome=row["outcome"],
            outcomeNote=row["outcomeNote"],
            createdAt=row["createdAt"],
        )


# GLOBAL FRAUD DB INSTANCE
fraud_db = FraudDatabase()

# Initialize mastery DB too
init_mastery_db()
