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
        "IMPORTANT: When your answer refers to information from a specific note, "
        "mention the note's exact title as written in the notes section below. "
        "Do not use numeric references like [1] or [2] — always use the note's title."
    )

    user = f"Notes:\n{contexts}\n\nQuestion: {question}\n\nAnswer:"

    return system, user


def format_contexts(contexts: list[dict]) -> str:
    """Format retrieved note contexts into a string.

    Args:
        contexts: List of note dictionaries with 'title' and 'content'

    Returns:
        Formatted string with numbered notes
    """
    parts = []
    for note in contexts:
        title = note.get("title", "Untitled")
        content = note.get("content", "")
        content = content[:2000]  # Limit context length
        parts.append(f"--- {title} ---\n{content}")
    return "\n\n".join(parts)


def build_chunk_relevance_prompt(chunk_content: str, question: str) -> tuple[str, str]:
    """Build the system and user prompt for chunk relevance evaluation.

    Args:
        chunk_content: The text content of the chunk to evaluate.
            Will be truncated by the caller to avoid token overruns.
        question: The user's question.

    Returns:
        Tuple of (system_message, user_prompt).
    """
    system = (
        "You are a relevance judge. Your sole task is to decide if a text chunk "
        "is relevant to a question. Respond with a single word: YES or NO."
    )
    user = (
        f"Question: {question}\n\n"
        f"Text chunk:\n{chunk_content}\n\n"
        "Is this chunk relevant to the question above? Answer YES or NO only."
    )
    return system, user
