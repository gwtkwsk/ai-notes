"""Shared prompt templates for RAG."""



def build_prompt(contexts: str, question: str) -> tuple[str, str]:
    """Build the system message and user prompt for the LLM.

    Args:
        contexts: Formatted context from retrieved notes
        question: User's question

    Returns:
        Tuple of (system_message, user_prompt)
    """
    system = (
        "You are an assistant that answers questions based on provided notes. "
        "If the answer is not in the notes, say so clearly. "
        "Answer concisely in Polish.\n\n"
        "IMPORTANT: Think step-by-step. First explain your reasoning, "
        "then provide the final answer. "
        "Show your work and thought process."
    )

    user = (
        f"Notes:\n{contexts}\n\n"
        f"Question: {question}\n\n"
        "Let me think through this step-by-step:"
    )

    return system, user


def format_contexts(contexts: list[dict]) -> str:
    """Format retrieved note contexts into a string.

    Args:
        contexts: List of note dictionaries with 'title' and 'content'

    Returns:
        Formatted string with numbered notes
    """
    parts = []
    for idx, note in enumerate(contexts, start=1):
        title = note.get("title", "Untitled")
        content = note.get("content", "")
        content = content[:2000]  # Limit context length
        parts.append(f"[{idx}] {title}\n{content}")
    return "\n\n".join(parts)
