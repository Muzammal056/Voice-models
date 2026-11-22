"""Preserve narration words while cleaning pasted document line wrapping."""
import re

def speech_paragraphs(text: str) -> list[str]:
    text=str(text).replace('\r\n','\n').replace('\r','\n')
    text=text.replace('\u00ad','').replace('\u200b','').replace('\ufeff','')
    # Rejoin words hyphenated by a document's line wrap, not normal compounds.
    text=re.sub(r'(?<=[A-Za-z])-\n[ \t]*(?=[a-z])','',text)
    paragraphs=re.split(r'\n[ \t]*\n+',text.strip())
    return [' '.join(paragraph.split()) for paragraph in paragraphs if paragraph.strip()]
