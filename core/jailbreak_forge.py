"""Jailbreak SHIELD only."""
import re
P=[r'(?i)\bDAN\b',r'(?i)\bignore\b',r'(?i)\bjailbreak\b']
D=[(r'(?i)\b(create|write)\b.*\b(malware|ransomware)\b','MALWARE')]
class JailbreakForge:
    def __init__(self): self._jb=[re.compile(p) for p in P]; self._di=[(re.compile(p),t) for p,t in D]
    def shield_scan(self,text,**kw):
        d,b=[],False
        for p in self._jb:
            if p.search(text): d.append("JB")
        for p,t in self._di:
            if p.search(text): d.append(t); b=True
        th="BLOCKED" if b else ("SUSPICIOUS" if d else "SAFE")
        return type('R',(),{'safe':th=='SAFE','threat_level':th,'detected_patterns':d,'blocked':b,'sanitized_input':text,'reason':';'.join(d)})()
