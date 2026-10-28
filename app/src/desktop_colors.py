"""Readable agent identity colours for the desktop UI."""
import re
from src.constants import AGENTCOLORLIST

def agent_color(player):
    name = str(player.get("agent", "")).casefold()
    rgb = AGENTCOLORLIST.get(name)
    if rgb is None:
        value = str(player.get("agentColor", "")).lstrip("#")
        rgb = tuple(int(value[i:i+2],16) for i in (0,2,4)) if re.fullmatch(r"[0-9a-fA-F]{6}([0-9a-fA-F]{2})?", value) else (195, 204, 222)
    def luminance(values):
        channels = [v/255 for v in values]
        channels = [v/12.92 if v<=0.04045 else ((v+0.055)/1.055)**2.4 for v in channels]
        return sum(v*w for v,w in zip(channels,(0.2126,0.7152,0.0722)))
    # Preserve the agent hue while making dark identities readable on selected cards.
    for step in range(21):
        amount=step/20
        result=tuple(round(v+(255-v)*amount) for v in rgb)
        if (luminance(result)+0.05)/(luminance((60,53,84))+0.05)>=4.5:
            return "#" + "".join(format(v,"02x") for v in result)
    return "#ffffff"