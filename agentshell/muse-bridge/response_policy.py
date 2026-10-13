"""Only a complete, plain greeting can bypass the tool-preamble settling wait."""
import re
import unicodedata

def greeting_only(text):
    if not isinstance(text,str) or len(text)>160:return False
    text=''.join(c for c in unicodedata.normalize('NFD',text.lower()) if unicodedata.category(c)!='Mn')
    text=re.sub(r'[^a-z0-9]+',' ',text).strip()
    text=re.sub(r'\b(muse|sagwa)\b','',text)
    text=' '.join(text.split())
    return bool(re.fullmatch(r'(hola|(?:hola )?(?:buenos dias|buenas tardes|buenas noches))',text))
