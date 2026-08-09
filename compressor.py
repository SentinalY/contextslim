import tiktoken
import nltk
from sumy.parsers.plaintext import PlaintextParser
from sumy.nlp.tokenizers import Tokenizer
from sumy.summarizers.lsa import LsaSummarizer

# Ensure required NLTK data is available for sumy's tokenizer
# Ensure required NLTK data is available for sumy's tokenizer
try:
    nltk.data.find('tokenizers/punkt')
    nltk.data.find('tokenizers/punkt_tab')
except LookupError:
    nltk.download('punkt', quiet=True)
    nltk.download('punkt_tab', quiet=True)
def count_tokens(text: str) -> int:
    """Count tokens using standard cl100k_base encoding."""
    enc = tiktoken.get_encoding("cl100k_base")
    return len(enc.encode(text))

def compress_slim(text: str, sentence_count: int = 5) -> dict:
    """
    Compresses conversation text using LSA.
    Returns the summary string and token reduction statistics.
    """
    tokens_before = count_tokens(text)
    
    # Handle empty or extremely short text edge cases
    if not text.strip():
        return {"summary": "", "tokens_before": 0, "tokens_after": 0}

    parser = PlaintextParser.from_string(text, Tokenizer("english"))
    summarizer = LsaSummarizer()
    
    # Extract the most important sentences based on LSA
    summary_sentences = summarizer(parser.document, sentence_count)
    summary_text = " ".join([str(sentence) for sentence in summary_sentences])
    
    tokens_after = count_tokens(summary_text)
    
    return {
        "summary": summary_text,
        "tokens_before": tokens_before,
        "tokens_after": tokens_after
    }
import os
import json
from dotenv import load_dotenv
from google import genai

load_dotenv()

_client = None

def _get_client():
    global _client
    if _client is None:
        _client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    return _client

DEEP_COMPRESSION_PROMPT = """You are compressing an AI coding session into a structured memory capsule.
Read the conversation below and produce a JSON object with exactly these 6 keys:

- "PROJECT": one sentence describing what is being built
- "COMPLETED": bullet list (as a single string, newline separated) of what has been finished
- "DECISIONS": bullet list of key technical decisions made and why
- "CURRENT_STATE": one or two sentences on where things stand right now
- "NEXT_OBJECTIVE": the single next concrete task to do
- "CONSTRAINTS": any limitations, requirements, or things to avoid, as a bullet list

Respond with ONLY the raw JSON object. No markdown code fences, no preamble, no explanation.

Conversation:
{conversation}
"""


def compress_deep(text: str) -> dict:
    """
    Compresses conversation text into a structured 6-section Context Capsule
    using Gemini Flash. Returns the structured capsule plus token stats.
    """
    tokens_before = count_tokens(text)

    if not text.strip():
        return {"summary": {}, "tokens_before": 0, "tokens_after": 0}

    prompt = DEEP_COMPRESSION_PROMPT.format(conversation=text)

    response = _get_client().models.generate_content(
    model="gemini-2.5-flash",
    contents=prompt,
)
    raw_output = response.text.strip()

    # Gemini sometimes wraps JSON in ```json fences despite instructions — strip if present
    if raw_output.startswith("```"):
        raw_output = raw_output.strip("`")
        if raw_output.startswith("json"):
            raw_output = raw_output[4:].strip()

    try:
        structured_summary = json.loads(raw_output)
    except json.JSONDecodeError:
        structured_summary = {"PROJECT": raw_output}

    tokens_after = count_tokens(json.dumps(structured_summary))

    return {
        "summary": structured_summary,
        "tokens_before": tokens_before,
        "tokens_after": tokens_after,
    }