"""Story 8 QA: Automated multi-turn conversation tests against live LLMs.

Exercises the WorkflowEngine with real OpenAI API calls through the
reception_flow.json workflow. Each test simulates a different caller
scenario and validates routing decisions, scope enforcement, and
context passing.

Run:  cd server && uv run python scripts/qa_workflow.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time

# Add server root to path so app.* imports work
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.llm.openai import LLMClient
from app.workflow.engine import WorkflowEngine

WORKFLOW_PATH = os.path.join(
    os.path.dirname(__file__), "..", "schemas", "examples", "reception_flow.json"
)

# ANSI colours for terminal output
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
BOLD = "\033[1m"
RESET = "\033[0m"

passed = 0
failed = 0


def load_workflow() -> dict:
    with open(WORKFLOW_PATH) as f:
        return json.load(f)


def _make_engine(workflow: dict) -> WorkflowEngine:
    """Create a fresh engine with real LLM clients."""
    responder = LLMClient(model="gpt-4o")
    router = LLMClient(model="gpt-4o-mini")
    return WorkflowEngine(workflow, responder=responder, router=router)


def _print_exchange(role: str, text: str) -> None:
    """Pretty-print a conversation exchange."""
    if role == "caller":
        print(f"  {YELLOW}Caller:{RESET} {text}")
    else:
        print(f"  {CYAN}Agent:{RESET}  {text}")


def _assert(condition: bool, description: str) -> None:
    """Check a condition and print pass/fail."""
    global passed, failed
    if condition:
        passed += 1
        print(f"    {GREEN}✓ {description}{RESET}")
    else:
        failed += 1
        print(f"    {RED}✗ {description}{RESET}")


# ======================================================================
# Test 1: Booking path — greeting → intent_router → book_appointment
# ======================================================================

async def test_booking_path():
    """Caller wants to book a dental cleaning. Should route to booking node."""
    print(f"\n{BOLD}{'=' * 60}{RESET}")
    print(f"{BOLD}TEST 1: Direct booking path{RESET}")
    print(f"{BOLD}{'=' * 60}{RESET}")

    wf = load_workflow()
    engine = _make_engine(wf)

    t0 = time.perf_counter()

    # Start — should get greeting from the greeting node
    greeting = await engine.start()
    _print_exchange("agent", greeting)
    _assert(engine.current_node.id == "greeting", "Starts at greeting node")
    _assert(len(greeting) > 10, "Greeting is non-empty")

    # Caller states intent to book
    _print_exchange("caller", "I'd like to book an appointment for a cleaning please")
    response, ended = await engine.handle_input(
        "I'd like to book an appointment for a cleaning please"
    )
    _print_exchange("agent", response)
    _assert(
        engine.current_node.id == "book_appointment",
        f"Routed to book_appointment (got: {engine.current_node.id})",
    )
    _assert(ended is False, "Call not ended")

    # Continue in booking node — give name
    _print_exchange("caller", "My name is Sarah Johnson")
    response2, ended2 = await engine.handle_input("My name is Sarah Johnson")
    _print_exchange("agent", response2)
    _assert(engine.current_node.id == "book_appointment", "Still in booking node")
    _assert(ended2 is False, "Call not ended")

    # Ask for time slot
    _print_exchange("caller", "How about next Wednesday at 2pm?")
    response3, ended3 = await engine.handle_input("How about next Wednesday at 2pm?")
    _print_exchange("agent", response3)
    _assert(engine.current_node.id == "book_appointment", "Still in booking node")

    elapsed = time.perf_counter() - t0
    print(f"\n  ⏱ Total time: {elapsed:.1f}s")
    _assert(len(engine.summaries) >= 1, "At least 1 summary generated (greeting)")


# ======================================================================
# Test 2: General inquiry path — greeting → intent_router → general_inquiry
# ======================================================================

async def test_inquiry_path():
    """Caller asks about prices. Should route to general_inquiry."""
    print(f"\n{BOLD}{'=' * 60}{RESET}")
    print(f"{BOLD}TEST 2: General inquiry path{RESET}")
    print(f"{BOLD}{'=' * 60}{RESET}")

    wf = load_workflow()
    engine = _make_engine(wf)

    t0 = time.perf_counter()

    greeting = await engine.start()
    _print_exchange("agent", greeting)

    # Ask about pricing
    _print_exchange("caller", "How much does a teeth whitening cost?")
    response, ended = await engine.handle_input(
        "How much does a teeth whitening cost?"
    )
    _print_exchange("agent", response)
    _assert(
        engine.current_node.id == "general_inquiry",
        f"Routed to general_inquiry (got: {engine.current_node.id})",
    )
    # The inquiry node has pricing data — check the response mentions a price
    _assert(
        "$" in response or "250" in response or "dollar" in response.lower(),
        "Response includes pricing information",
    )

    # Follow-up question
    _print_exchange("caller", "What are your opening hours?")
    response2, _ = await engine.handle_input("What are your opening hours?")
    _print_exchange("agent", response2)
    _assert(engine.current_node.id == "general_inquiry", "Still in inquiry node")
    _assert(
        any(w in response2.lower() for w in ["9", "5", "monday", "friday", "hours"]),
        "Response mentions hours info",
    )

    elapsed = time.perf_counter() - t0
    print(f"\n  ⏱ Total time: {elapsed:.1f}s")


# ======================================================================
# Test 3: Speak to human path
# ======================================================================

async def test_human_path():
    """Caller asks to speak with a real person. Should route to speak_to_human."""
    print(f"\n{BOLD}{'=' * 60}{RESET}")
    print(f"{BOLD}TEST 3: Speak to human path{RESET}")
    print(f"{BOLD}{'=' * 60}{RESET}")

    wf = load_workflow()
    engine = _make_engine(wf)

    t0 = time.perf_counter()

    greeting = await engine.start()
    _print_exchange("agent", greeting)

    _print_exchange("caller", "Can I speak with a real person please?")
    response, ended = await engine.handle_input(
        "Can I speak with a real person please?"
    )
    _print_exchange("agent", response)
    _assert(
        engine.current_node.id == "speak_to_human",
        f"Routed to speak_to_human (got: {engine.current_node.id})",
    )
    _assert(
        any(w in response.lower() for w in ["connect", "transfer", "team", "staff", "member", "person"]),
        "Response mentions connecting to a person",
    )

    elapsed = time.perf_counter() - t0
    print(f"\n  ⏱ Total time: {elapsed:.1f}s")


# ======================================================================
# Test 4: Re-routing — booking → change mind → inquiry
# ======================================================================

async def test_reroute_booking_to_inquiry():
    """Caller starts booking, then asks about prices. Should re-route."""
    print(f"\n{BOLD}{'=' * 60}{RESET}")
    print(f"{BOLD}TEST 4: Re-route from booking to inquiry{RESET}")
    print(f"{BOLD}{'=' * 60}{RESET}")

    wf = load_workflow()
    engine = _make_engine(wf)

    t0 = time.perf_counter()

    greeting = await engine.start()
    _print_exchange("agent", greeting)

    # First: route to booking
    _print_exchange("caller", "I want to book a checkup")
    r1, _ = await engine.handle_input("I want to book a checkup")
    _print_exchange("agent", r1)
    _assert(
        engine.current_node.id == "book_appointment",
        f"Initially routed to booking (got: {engine.current_node.id})",
    )

    # Interact in booking node
    _print_exchange("caller", "My name is Alex")
    r2, _ = await engine.handle_input("My name is Alex")
    _print_exchange("agent", r2)

    # Change mind — ask about prices (should re-route via intent_router → general_inquiry)
    _print_exchange("caller", "Actually wait, how much does a filling cost?")
    r3, _ = await engine.handle_input(
        "Actually wait, how much does a filling cost?"
    )
    _print_exchange("agent", r3)
    _assert(
        engine.current_node.id == "general_inquiry",
        f"Re-routed to general_inquiry (got: {engine.current_node.id})",
    )

    # The first response in the new node may be generic ("How can I help?") since
    # the triggering question lives in the summary, not the fresh node history.
    # Follow up to confirm pricing data is accessible.
    _print_exchange("caller", "How much is a filling?")
    r4, _ = await engine.handle_input("How much is a filling?")
    _print_exchange("agent", r4)
    _assert(
        "$" in r4 or "150" in r4 or "300" in r4 or "filling" in r4.lower(),
        "Inquiry node has filling pricing info",
    )

    elapsed = time.perf_counter() - t0
    print(f"\n  ⏱ Total time: {elapsed:.1f}s")
    _assert(
        len(engine.summaries) >= 2,
        f"At least 2 summaries generated (got: {len(engine.summaries)})",
    )


# ======================================================================
# Test 5: Scope enforcement — booking node deflects off-topic questions
# ======================================================================

async def test_scope_enforcement():
    """Booking node should not answer pricing questions directly."""
    print(f"\n{BOLD}{'=' * 60}{RESET}")
    print(f"{BOLD}TEST 5: Scope enforcement in booking node{RESET}")
    print(f"{BOLD}{'=' * 60}{RESET}")

    wf = load_workflow()
    engine = _make_engine(wf)

    t0 = time.perf_counter()

    greeting = await engine.start()
    _print_exchange("agent", greeting)

    # Route to booking
    _print_exchange("caller", "I need to book a dental appointment")
    r1, _ = await engine.handle_input("I need to book a dental appointment")
    _print_exchange("agent", r1)
    _assert(
        engine.current_node.id == "book_appointment",
        f"Routed to booking (got: {engine.current_node.id})",
    )

    # Ask an off-topic question — the booking node should NOT answer with
    # pricing details, it should deflect / re-route
    _print_exchange("caller", "What is the meaning of life?")
    r2, _ = await engine.handle_input("What is the meaning of life?")
    _print_exchange("agent", r2)

    # The response should NOT contain a philosophical answer
    philosophy_words = ["purpose", "42", "happiness", "meaning of life", "existential"]
    has_philosophy = any(w in r2.lower() for w in philosophy_words)
    _assert(
        not has_philosophy,
        "Booking node does not answer philosophical questions",
    )

    elapsed = time.perf_counter() - t0
    print(f"\n  ⏱ Total time: {elapsed:.1f}s")


# ======================================================================
# Test 6: Context carries across nodes
# ======================================================================

async def test_context_carries_across():
    """Information from greeting carries to the booking node via summaries."""
    print(f"\n{BOLD}{'=' * 60}{RESET}")
    print(f"{BOLD}TEST 6: Context carries across nodes{RESET}")
    print(f"{BOLD}{'=' * 60}{RESET}")

    wf = load_workflow()
    engine = _make_engine(wf)

    t0 = time.perf_counter()

    greeting = await engine.start()
    _print_exchange("agent", greeting)

    # Mention name and intent in the greeting node
    _print_exchange("caller", "Hi, my name is Emily and I'd like to book a cleaning")
    r1, _ = await engine.handle_input(
        "Hi, my name is Emily and I'd like to book a cleaning"
    )
    _print_exchange("agent", r1)
    _assert(
        engine.current_node.id == "book_appointment",
        f"Routed to booking (got: {engine.current_node.id})",
    )

    # Check that the summary captured the name
    _assert(len(engine.summaries) >= 1, "Summary generated from greeting node")
    all_summary_text = " ".join(
        s.summary + " " + json.dumps(s.key_info) for s in engine.summaries
    )
    _assert(
        "emily" in all_summary_text.lower() or "Emily" in all_summary_text,
        f"Summary captured caller's name 'Emily'",
    )

    # The booking node response should ideally use the name
    # (it has the summary context prefix)
    _print_exchange("caller", "I'd prefer Tuesday at 10am for the cleaning")
    r2, _ = await engine.handle_input("I'd prefer Tuesday at 10am for the cleaning")
    _print_exchange("agent", r2)
    _assert(engine.current_node.id == "book_appointment", "Still in booking node after scheduling")

    elapsed = time.perf_counter() - t0
    print(f"\n  ⏱ Total time: {elapsed:.1f}s")


# ======================================================================
# Test 7: Multi-hop re-routing — inquiry → booking
# ======================================================================

async def test_reroute_inquiry_to_booking():
    """Caller asks about prices, then decides to book. Should re-route."""
    print(f"\n{BOLD}{'=' * 60}{RESET}")
    print(f"{BOLD}TEST 7: Re-route from inquiry to booking{RESET}")
    print(f"{BOLD}{'=' * 60}{RESET}")

    wf = load_workflow()
    engine = _make_engine(wf)

    t0 = time.perf_counter()

    greeting = await engine.start()
    _print_exchange("agent", greeting)

    # Start with a question
    _print_exchange("caller", "How much is a checkup?")
    r1, _ = await engine.handle_input("How much is a checkup?")
    _print_exchange("agent", r1)
    _assert(
        engine.current_node.id == "general_inquiry",
        f"Routed to inquiry (got: {engine.current_node.id})",
    )

    # Now want to book
    _print_exchange("caller", "Great, I'd like to book one please")
    r2, _ = await engine.handle_input("Great, I'd like to book one please")
    _print_exchange("agent", r2)
    _assert(
        engine.current_node.id == "book_appointment",
        f"Re-routed to booking (got: {engine.current_node.id})",
    )

    elapsed = time.perf_counter() - t0
    print(f"\n  ⏱ Total time: {elapsed:.1f}s")
    _assert(
        len(engine.summaries) >= 2,
        f"At least 2 summaries generated (got: {len(engine.summaries)})",
    )


# ======================================================================
# Main
# ======================================================================

async def main():
    global passed, failed

    print(f"{BOLD}Story 8 QA — Automated Workflow Engine Tests (Live LLM){RESET}")
    print(f"Using reception_flow.json with real OpenAI API calls.\n")

    tests = [
        ("Booking path", test_booking_path),
        ("Inquiry path", test_inquiry_path),
        ("Speak to human path", test_human_path),
        ("Re-route: booking → inquiry", test_reroute_booking_to_inquiry),
        ("Scope enforcement", test_scope_enforcement),
        ("Context carries across nodes", test_context_carries_across),
        ("Re-route: inquiry → booking", test_reroute_inquiry_to_booking),
    ]

    results = []
    for name, test_fn in tests:
        before_failed = failed
        try:
            await test_fn()
            results.append((name, "PASS" if failed == before_failed else "PARTIAL"))
        except Exception as e:
            failed += 1
            results.append((name, "ERROR"))
            print(f"    {RED}✗ Test raised exception: {e}{RESET}")

    # Summary
    print(f"\n{'=' * 60}")
    print(f"{BOLD}RESULTS SUMMARY{RESET}")
    print(f"{'=' * 60}")
    for name, status in results:
        icon = GREEN + "✓" if status == "PASS" else (YELLOW + "~" if status == "PARTIAL" else RED + "✗")
        print(f"  {icon} {name}{RESET}")

    print(f"\n  {BOLD}Assertions: {GREEN}{passed} passed{RESET}, ", end="")
    if failed:
        print(f"{RED}{failed} failed{RESET}")
    else:
        print(f"{GREEN}0 failed{RESET}")

    total = passed + failed
    if failed == 0:
        print(f"\n{GREEN}{BOLD}ALL {total} ASSERTIONS PASSED ✓{RESET}")
    else:
        print(f"\n{YELLOW}{BOLD}{passed}/{total} ASSERTIONS PASSED{RESET}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
