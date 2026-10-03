#!/usr/bin/env python3
"""Render an original captioned schematic explainer; never capture live UI.

Optional documentation tooling: Pillow and an ffmpeg build with libx264.
The installer itself has no dependency on either program.
"""
import argparse
import math
from pathlib import Path
import shutil
import subprocess

from PIL import Image, ImageDraw, ImageFont

DURATION = 32
WIDTH, HEIGHT = 1280, 720
BG, INK, MUTED = "#F4F5F1", "#192D26", "#65756C"
GREEN, LIGHT, BORDER = "#287653", "#DCEFE3", "#DCE3DC"
SCENES = [
    (0, 3, "Codex with your MX Master 4", "One click. The right action.", None),
    (3, 8, "Start dictation", "Back button  ·  Ctrl + Shift + D", "back"),
    (8, 13, "Start voice chat", "Upper side button  ·  Ctrl + Shift + V", "voice"),
    (13, 18, "Confirm with Enter", "Forward button  ·  Focus the control you want to confirm", "forward"),
    (18, 23, "Switch between chats", "Thumb wheel  ·  Cmd + Option + Left / Right Arrow", "wheel"),
    (23, 29, "Open the Actions Ring", "Haptic thumb pad  ·  Eight actions under your thumb", "ring"),
    (29, 32, "Your shortcuts, right at your fingertips", "Dictate. Talk. Confirm. Navigate.", None),
]
CONTROLS = {
    "voice": (186, 357, "Upper side button"),
    "forward": (208, 417, "Forward button"),
    "back": (208, 486, "Back button"),
    "wheel": (248, 451, "Thumb wheel"),
    "attention": (284, 282, "Middle button"),
    "ring": (143, 464, "Haptic thumb pad"),
}


def bezier(a, b, c, d, steps=36):
    result = []
    for i in range(steps + 1):
        t = i / steps
        result.append(((1-t)**3*a[0] + 3*(1-t)**2*t*b[0] + 3*(1-t)*t*t*c[0] + t**3*d[0],
                       (1-t)**3*a[1] + 3*(1-t)**2*t*b[1] + 3*(1-t)*t*t*c[1] + t**3*d[1]))
    return result


class Demo:
    def __init__(self, scale=2):
        self.scale = scale
        candidates = [
            ("/System/Library/Fonts/Supplemental/Arial.ttf", "/System/Library/Fonts/Supplemental/Arial Bold.ttf"),
            ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
            ("C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/arialbd.ttf"),
        ]
        self.font_paths = next(((a, b) for a, b in candidates if Path(a).is_file() and Path(b).is_file()), None)
        if self.font_paths is None:
            raise RuntimeError("Install Arial or DejaVu Sans to render the demo")
        self.fonts = {}
        self.image = Image.new("RGB", (WIDTH*scale, HEIGHT*scale), BG)
        self.draw = ImageDraw.Draw(self.image)
        self.rect((40, 153, 419, 627), fill="#FFFFFF", radius=24, outline=BORDER)
        self.text((61, 180), "MX Master 4", 18, bold=True)
        self.text((61, 205), "Schematic illustration", 14, color=MUTED)
        self.mouse()
        self.base = self.image.copy()

    def font(self, size, bold=False):
        key = size, bold
        if key not in self.fonts:
            self.fonts[key] = ImageFont.truetype(self.font_paths[int(bold)], round(size*self.scale))
        return self.fonts[key]

    def text(self, point, text, size=22, color=INK, bold=False, anchor=None):
        self.draw.text(tuple(x*self.scale for x in point), text, fill=color,
                       font=self.font(size, bold), anchor=anchor, align="center" if anchor=="mm" else "left", spacing=5*self.scale)

    def rect(self, box, fill, radius=12, outline=None, width=1):
        self.draw.rounded_rectangle(tuple(round(x*self.scale) for x in box), radius=radius*self.scale,
                                    fill=fill, outline=outline, width=width*self.scale)

    def line(self, points, fill, width=2):
        self.draw.line([(round(x*self.scale), round(y*self.scale)) for x, y in points], fill=fill, width=width*self.scale)

    def circle(self, center, radius, fill=None, outline=None, width=1):
        x, y = center
        self.draw.ellipse(tuple(round(v*self.scale) for v in (x-radius,y-radius,x+radius,y+radius)),
                          fill=fill, outline=outline, width=width*self.scale)

    def polygon(self, points, fill):
        self.draw.polygon([(round(x*self.scale),round(y*self.scale)) for x,y in points], fill=fill)

    def mouse(self):
        curves = [
            ((235,235),(265,223),(304,251),(329,319)),
            ((329,319),(360,393),(366,494),(328,552)),
            ((328,552),(299,596),(224,602),(161,565)),
            ((161,565),(101,558),(89,517),(106,459)),
            ((106,459),(122,402),(158,391),(174,346)),
            ((174,346),(181,286),(198,245),(235,235)),
        ]
        outline = [point for curve in curves for point in bezier(*curve)]
        shadow = [(x+7,y+8) for x,y in outline]
        self.polygon(shadow, "#E7EBE6")
        self.polygon(outline, "#C7CECA")
        top = bezier((236,239),(279,229),(322,296),(331,383)) + bezier((331,383),(335,450),(317,520),(298,554)) + bezier((298,554),(271,578),(247,579),(229,554)) + bezier((229,554),(204,482),(191,327),(236,239))
        self.polygon(top, "#DCE1DE")
        self.line(bezier((242,242),(232,305),(236,354),(326,385)), "#A6B1A9", 2)
        self.line(bezier((174,383),(155,432),(153,480),(200,544)), "#ADB9B0", 2)
        for i in range(9):
            self.line(bezier((115+i*3,474+i*6),(137,447+i*8),(157,478+i*8),(174,529+i*4)), "#BCC7BF", 1)
        # Main wheel and two stacked navigation buttons.
        self.rect((270,253,297,314), "#76847B", radius=9)
        self.rect((277,258,291,309), "#C2CBC4", radius=5)
        for y in range(264,306,6): self.line([(278,y),(290,y)], "#65766B", 1)
        self.rect((176,334,196,378), "#8B9A90", radius=9)
        self.rect((181,339,191,373), "#EDF0ED", radius=5)
        self.rect((196,392,219,443), "#87988D", radius=9)
        self.rect((201,399,215,438), "#ECF0ED", radius=6)
        self.rect((196,460,219,511), "#87988D", radius=9)
        self.rect((201,466,215,505), "#ECF0ED", radius=6)
        # Thumb wheel and haptic pad are separate controls.
        self.rect((232,411,263,491), "#6B7E71", radius=8)
        for y in range(418,486,5): self.line([(236,y),(259,y)], "#BAC7BD", 2)
        self.rect((122,437,164,491), "#9AAA9F", radius=15)
        for r in (6,12,18): self.circle((143,464),r,outline="#C4D1C7",width=1)
        self.text((287,409), "MX", 27, color="#A1AEA5", bold=True, anchor="mm")

    def app(self, selected="Website", attention=False):
        self.rect((450,153,1240,627), fill="#FFFFFF", radius=24, outline=BORDER)
        self.rect((452,155,637,625), fill="#EEF2ED", radius=22)
        self.rect((614,155,637,625), fill="#EEF2ED", radius=0)
        self.text((474,189), "CODEX", 17, bold=True)
        self.text((474,229), "Chats", 15, color=MUTED)
        for i, label in enumerate(("Website","Tests","Documentation")):
            y = 252 + i*65
            if label == selected: self.rect((464,y,622,y+48), LIGHT, radius=10)
            self.text((480,y+24), label, 17, bold=label==selected, anchor="lm")
            if label == "Tests": self.circle((607,y+24),4,fill="#C28632")
        self.text((666,186), selected, 20, bold=True)
        self.line([(654,215),(1220,215)],BORDER,1)
        self.text((666,240), "Example chat", 15, color=MUTED)
        if attention:
            self.rect((681,326,1193,420), "#FFF3DD", radius=15)
            self.text((704,350), "This chat needs you.", 23, bold=True)
            self.text((704,386), "A response is waiting.", 19, color=MUTED)

    def composer(self, text="", status=None):
        self.rect((665,513,1220,604), "#FAFCF9", radius=15, outline=BORDER)
        self.text((687,539), text or "Write a message …", 19, color=INK if text else MUTED)
        self.circle((1186,574),14,fill=GREEN if text else "#D8E1D9")
        self.text((1186,574), "↑", 19, color="#FFFFFF", bold=True, anchor="mm")
        if status: self.text((687,580), status, 15, color=GREEN)

    def highlight(self, control, t):
        x,y,label=CONTROLS[control]
        pulse=0.5+0.5*math.sin(t*math.pi*2)
        self.circle((x,y),26+pulse*4,outline=LIGHT,width=6)
        self.circle((x,y),21,outline=GREEN,width=3)
        self.circle((x,y),5,fill=GREEN)
        self.rect((58,578,401,612),"#F2F7F2",radius=10)
        self.text((229,595),label,21,bold=True,anchor="mm")

    def wave(self, center, t, width=160, color=GREEN):
        x,y=center
        for i in range(19):
            h=10+29*abs(math.sin(t*3+i*0.8))*math.sin(math.pi*(i+1)/20)
            xx=x-width/2+i*width/18
            self.rect((xx-2,y-h/2,xx+2,y+h/2),color,radius=2)

    def ring(self, local):
        center=(934,414)
        labels=("Plan\nmode","Fast\nmode","Fork\nchat","Reasoning\n+", "Reasoning\n−","Mute\nmic","Review","Needs\nattention")
        self.circle(center,130,fill="#F0F6F0",outline="#D0E3D5",width=2)
        chosen=min(7,max(0,int((local-1.2)*1.3)))
        for i,label in enumerate(labels):
            angle=-math.pi/2+i*math.pi/4
            x=center[0]+164*math.cos(angle); y=center[1]+164*math.sin(angle)
            self.line([center,(x,y)],"#CBDCD0",2)
            active=i==chosen and local>1.2
            self.rect((x-56,y-30,x+56,y+30), GREEN if active else "#FFFFFF", radius=13,outline=BORDER)
            self.text((x,y),label,20,color="#FFFFFF" if active else INK,bold=True,anchor="mm")
        self.circle(center,56,fill="#FFFFFF",outline=BORDER,width=2)
        self.text((934,405),"ACTIONS",15,bold=True,anchor="mm")
        self.text((934,428),"RING",18,bold=True,anchor="mm")

    def overview(self):
        self.app()
        self.text((670,283), "Your shortcuts, within reach", 26, bold=True)
        rows=("Back   →   Start dictation", "Upper side   →   Start voice chat", "Haptic pad   →   Actions Ring", "Forward   →   Enter", "Thumb wheel   →   Switch chats", "Middle   →   Needs attention")
        for i,row in enumerate(rows):
            self.circle((680,336+i*43),4,fill=GREEN)
            self.text((697,336+i*43),row,22,anchor="lm")

    def frame(self,t):
        self.image=self.base.copy(); self.draw=ImageDraw.Draw(self.image)
        index=next(i for i,scene in enumerate(SCENES) if scene[0]<=t<scene[1])
        start,end,title,subtitle,control=SCENES[index]; local=t-start
        footer="Animated explanation  ·  Example view  ·  Codex in the foreground"
        if index in (0,6):
            self.overview()
        elif index==1:
            self.app(); phrase="Create a clear and simple home page."
            amount=max(0,min(len(phrase),int((local-0.8)*len(phrase)/2.9)))
            self.text((942,347),"Dictation is on",26,bold=True,anchor="mm")
            self.wave((943,412),local)
            self.composer(phrase[:amount],"Speech becomes text")
            footer="Start dictation  ·  Press again to stop"
        elif index==2:
            self.app()
            self.circle((942,365),62,fill=LIGHT)
            self.wave((942,365),local,width=81)
            self.text((942,471),"Voice chat is active",28,bold=True,anchor="mm")
            self.text((942,515),"In the current chat",20,color=MUTED,anchor="mm")
            footer="Start voice chat  ·  Press again to stop"
        elif index==3:
            self.app(); self.composer()
            self.rect((685,296,1190,371),"#F0F4EF",radius=15)
            self.text((706,332),"The change is ready.",23,anchor="lm")
            if local<1.8:
                self.rect((863,401,1069,457),"#FFFFFF",radius=13,outline=GREEN,width=3)
                self.text((966,429),"Confirm",23,bold=True,anchor="mm")
                self.text((966,483),"This button has focus",17,color=MUTED,anchor="mm")
            else:
                self.rect((863,401,1069,457),GREEN,radius=13)
                self.text((966,429),"Confirmed",23,color="#FFFFFF",bold=True,anchor="mm")
            footer="Enter acts on the focused control."
        elif index==4:
            attention=local>=3.1
            selected="Website" if local<1 else "Tests" if local<2 else "Documentation"
            if attention: selected="Tests"; control="attention"; title="Open a chat that needs attention"; subtitle="Middle button  ·  Cmd + Option + A"
            self.app(selected,attention)
            if not attention:
                self.text((943,364),"←   Switch chat   →",27,bold=True,anchor="mm")
                self.text((943,409),"Previous / next chat",21,color=MUTED,anchor="mm")
            self.composer()
            footer="Follows Codex's navigation order across all chats."
        else:
            self.app(); self.ring(local)
            footer="Press the haptic thumb pad  →  Choose an action"
        if control: self.highlight(control,local)
        else:
            self.text((229,596),"Six mouse controls",21,bold=True,anchor="mm")
        self.text((48,32),"CODEX  ×  MX MASTER 4",16,bold=True,color=GREEN)
        self.text((48,72),title,36,bold=True)
        self.text((50,119),subtitle,19,color=MUTED)
        self.rect((1051,26,1234,60),LIGHT,radius=17)
        self.text((1142,43),"Animated explanation",15,bold=True,color=GREEN,anchor="mm")
        self.text((50,665),footer,18,color=MUTED)
        self.text((1230,665),f"{index+1:02d} / 07",17,color=MUTED,anchor="rm")
        self.rect((48,704,1232,708),"#DFE7DF",radius=2)
        self.rect((48,704,48+1184*(t/DURATION),708),GREEN,radius=2)
        return self.image.resize((WIDTH,HEIGHT),Image.Resampling.LANCZOS)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mp4",type=Path,required=True)
    parser.add_argument("--gif",type=Path,required=True)
    parser.add_argument("--previews",type=Path)
    parser.add_argument("--fps",type=int,default=24)
    args=parser.parse_args()
    if args.fps<12 or args.fps>60: parser.error("fps must be 12..60")
    ffmpeg=shutil.which("ffmpeg")
    if not ffmpeg: parser.error("ffmpeg is required")
    for path in (args.mp4,args.gif): path.parent.mkdir(parents=True,exist_ok=True)
    demo=Demo()
    if args.previews:
        args.previews.mkdir(parents=True,exist_ok=True)
        for i,t in enumerate((1.5,5.5,10.5,15.5,20.4,26.0,30.5)):
            demo.frame(t).save(args.previews/f"scene-{i+1:02d}.png")
    command=[ffmpeg,"-y","-hide_banner","-loglevel","error","-f","rawvideo","-pix_fmt","rgb24",
             "-s",f"{WIDTH}x{HEIGHT}","-r",str(args.fps),"-i","pipe:0","-an","-c:v","libx264",
             "-preset","medium","-crf","24","-pix_fmt","yuv420p","-movflags","+faststart",str(args.mp4)]
    process=subprocess.Popen(command,stdin=subprocess.PIPE)
    try:
        for frame in range(DURATION*args.fps):
            if frame% (4*args.fps)==0: print(f"Rendering {frame//args.fps}/{DURATION} s",flush=True)
            process.stdin.write(demo.frame(frame/args.fps).tobytes())
        process.stdin.close()
        if process.wait(): raise RuntimeError("Video encoding failed")
    except BaseException:
        process.kill(); process.wait(); raise
    subprocess.run([ffmpeg,"-y","-hide_banner","-loglevel","error","-i",str(args.mp4),
                    "-filter_complex","fps=12,scale=960:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=96:stats_mode=diff[p];[b][p]paletteuse=dither=none:diff_mode=rectangle",
                    "-loop","0",str(args.gif)],check=True)
    print(f"Created {args.mp4} and {args.gif}",flush=True)


if __name__=="__main__": main()
