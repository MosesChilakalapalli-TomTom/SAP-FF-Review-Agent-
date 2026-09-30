# -*- coding: utf-8 -*-
"""Generates high-level architecture diagrams for the security onboarding doc."""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
from matplotlib.path import Path
import matplotlib.patches as mpatches

NAVY = "#1F3864"
BLUE = "#2E74B5"
LIGHT = "#DDEBF7"
GREEN = "#548235"
LIGHTGREEN = "#E2EFDA"
ORANGE = "#BF8F00"
LIGHTORANGE = "#FFF2CC"
GREY = "#404040"

def box(ax, x, y, w, h, text, facecolor=LIGHT, edgecolor=NAVY, fontsize=11, fontweight="bold", fontcolor=NAVY):
    b = FancyBboxPatch((x, y), w, h,
                        boxstyle="round,pad=0.02,rounding_size=0.06",
                        linewidth=1.8, edgecolor=edgecolor, facecolor=facecolor)
    ax.add_patch(b)
    ax.text(x + w / 2, y + h / 2, text, ha="center", va="center",
            fontsize=fontsize, fontweight=fontweight, color=fontcolor, wrap=True)
    return b

def arrow(ax, xy_from, xy_to, text=None, color=GREY, style="-|>", ls="-", rad=0.0, fontsize=9):
    a = FancyArrowPatch(xy_from, xy_to, arrowstyle=style, mutation_scale=16,
                         linewidth=1.6, color=color, linestyle=ls,
                         connectionstyle=f"arc3,rad={rad}")
    ax.add_patch(a)
    if text:
        mx, my = (xy_from[0] + xy_to[0]) / 2, (xy_from[1] + xy_to[1]) / 2
        ax.text(mx, my + 0.12, text, ha="center", va="bottom", fontsize=fontsize, color=GREY)

# -------------------------------------------------------------------
# DIAGRAM 1 — High level system architecture
# -------------------------------------------------------------------
fig, ax = plt.subplots(figsize=(11, 5.5))
ax.set_xlim(0, 11)
ax.set_ylim(0, 6)
ax.axis("off")

box(ax, 0.3, 2.2, 2.3, 1.6, "Employee\n(SAP Fiori Launchpad\n+ AI Assistant UI)", facecolor=LIGHT)
box(ax, 3.3, 3.9, 2.3, 1.4, "Microsoft Entra ID\n(company identity\nprovider)", facecolor=LIGHTGREEN, edgecolor=GREEN, fontcolor=GREEN)
box(ax, 3.3, 0.5, 2.3, 1.4, "Azure Function App\nEasy Auth  +  Python\nAI Backend", facecolor=LIGHT)
box(ax, 6.6, 0.5, 2.1, 1.4, "Azure OpenAI\n(answers questions)", facecolor=LIGHT)
box(ax, 6.6, 3.9, 2.3, 1.4, "SAP System\n(GRC Firefighter data)", facecolor=LIGHTORANGE, edgecolor=ORANGE, fontcolor=ORANGE)
box(ax, 9.1, 2.2, 1.6, 1.6, "Result shown\nto employee", facecolor=LIGHT)

# flows
arrow(ax, (1.45, 3.8), (3.9, 4.6), "1. Sign in", rad=0.15)
arrow(ax, (4.4, 3.9), (2.6, 3.8), "2. Access token", rad=0.15)
arrow(ax, (2.6, 2.9), (3.3, 1.8), "3. Question + token")
arrow(ax, (5.6, 1.2), (6.6, 1.2), "4. Answer request")
arrow(ax, (7.7, 1.9), (7.7, 3.9), "5. Firefighter\ncheck only", color=ORANGE)
arrow(ax, (5.6, 1.5), (9.1, 3.0), "6. Filtered\nresponse", rad=-0.2)

ax.text(5.5, 5.6, "High-level architecture: who talks to whom", ha="center", fontsize=14,
        fontweight="bold", color=NAVY)
ax.text(5.5, 0.05,
        "Note: The employee's browser never talks to SAP or Azure OpenAI directly — only the backend does, after it has verified who is asking.",
        ha="center", fontsize=9, color=GREY, style="italic")

plt.tight_layout()
plt.savefig("architecture_overview.png", dpi=200)
plt.close(fig)

# -------------------------------------------------------------------
# DIAGRAM 2 — Layered security / request flow (vertical swimlane)
# -------------------------------------------------------------------
fig, ax = plt.subplots(figsize=(9, 11))
ax.set_xlim(0, 9)
ax.set_ylim(0, 21)
ax.axis("off")

steps = [
    ("1. Employee signs in with company\nMicrosoft account (Microsoft Entra ID / MSAL)", LIGHT, NAVY),
    ("2. Employee's app receives a signed\naccess token proving their identity", LIGHT, NAVY),
    ("3. App sends the question + token to\nthe Azure Function backend", LIGHT, NAVY),
    ("4. Azure \u201cEasy Auth\u201d checks the token\nis valid, not expired, from the right tenant.\nInvalid tokens are rejected (HTTP 401)\nbefore any code runs.", LIGHTGREEN, GREEN),
    ("5. Backend reads the verified identity\n(email) that Azure already confirmed.\nAnything the browser sent is ignored\nfor identity purposes.", LIGHTGREEN, GREEN),
    ("6. Question is routed:\nGeneral question  \u2192  AI Assistant (RAG)\nFirefighter question \u2192 extra checks below", LIGHT, NAVY),
]
y = 19.4
box_h = 1.7
xs = []
for txt, fc, ec in steps:
    box(ax, 1.0, y - box_h, 7.0, box_h, txt, facecolor=fc, edgecolor=ec, fontsize=10, fontcolor=ec)
    xs.append(y - box_h / 2)
    y -= (box_h + 0.35)

for i in range(len(xs) - 1):
    arrow(ax, (4.5, xs[i] - box_h / 2 + 0.05), (4.5, xs[i + 1] + box_h / 2 - 0.05))

# Firefighter-only extra lane
ff_steps = [
    "7. Is this employee a registered\nFirefighter Controller? (backend list)",
    "8. SAP is asked to confirm this employee\nis authorised for Firefighter data",
    "9. SAP returns only the sessions/activities\nthat belong to this controller\n(nothing extra, nothing hidden)",
]
y2 = xs[-1] - box_h / 2 - 0.5
for txt in ff_steps:
    box(ax, 1.0, y2 - 1.4, 7.0, 1.4, txt, facecolor=LIGHTORANGE, edgecolor=ORANGE, fontsize=10, fontcolor=ORANGE)
    y2 -= 1.75

arrow(ax, (4.5, xs[-1] - box_h / 2 + 0.05), (4.5, y2 + 1.75 - 0.05 + 1.4), color=ORANGE)
for i in range(2):
    yy = xs[-1] - box_h / 2 - 0.5 - 1.75 * i
    arrow(ax, (4.5, yy - 1.4 + 0.05), (4.5, yy - 1.75 + 1.4 - 0.05), color=ORANGE)

box(ax, 1.0, y2 - 1.6, 7.0, 1.4, "10. Answer is shown to the employee\n(AI output is treated as untrusted text\nand safely displayed \u2014 no code execution)",
    facecolor=LIGHT, edgecolor=NAVY, fontsize=10, fontcolor=NAVY)
arrow(ax, (4.5, y2 - 1.4 + 0.05), (4.5, y2 - 1.6 + 1.4 - 0.05))

ax.text(4.5, 20.5, "Step-by-step: how one question is handled securely", ha="center",
        fontsize=14, fontweight="bold", color=NAVY)

plt.tight_layout()
plt.savefig("request_flow.png", dpi=200)
plt.close(fig)

print("Diagrams generated.")
