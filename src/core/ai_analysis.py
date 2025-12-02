# ai_analysis.py
from __future__ import annotations
import os
import json
from typing import Dict, Any

from openai import OpenAI

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

SYSTEM_PROMPT = """
Jsi odborník na český realitní trh. Analyzuješ bytové inzeráty a vracíš přísnou, technickou a realistickou analýzu.
Vstupní objekt `listing` může obsahovat pole jako například:
- `title`, `url`
- `locality`, `location`
- `price_czk`, `area_m2`, `dispo`, `price_per_m2`
- `description` (dlouhý popis z inzerátu)
- `raw_text` (text převzatý ze Slack zprávy / jiných zdrojů)
- případně další pomocná pole.

Jako hlavní textový zdroj používej spojený text z `description` (pokud je k dispozici) a `raw_text`.
Z těchto textů se snaž odvozovat informace jako:
- patro / podlaží (např. "ve 3. patře", "3. podlaží z 6"),
- typ stavby (novostavba / starší cihla / panel),
- výtah, sklep, balkón / terasa,
- vybavení bytu,
- termín nastěhování,
- kvalita lokality a dostupnost.

Pokud je v textu patrné podlaží (např. "ve 3. patře", "3. podlaží z 6", "4. NP" apod.), NEUVÁDĚJ tuto informaci v části `missing_critical_info` jako chybějící.
Analogicky – pokud z textu vyplývá, že byt je vybavený / částečně vybavený, nebo že je novostavba apod., nepiš, že tyto informace chybí.

Tvůj výstup MUSÍ být platný JSON přesně podle této struktury:

{
  "overall_comment": "1-3 věty shrnutí pro běžného uživatele.",
  "price_assessment": {
    "verdict": "podhodnocená | odpovídající | nadhodnocená | nelze_posoudit",
    "comment": "Stručné vysvětlení proč.",
    "confidence": 1-5,
    "price_per_m2_estimate": {
      "listing_price_per_m2": null nebo číslo,
      "expected_range_min": null nebo číslo,
      "expected_range_max": null nebo číslo
    }
  },
  "red_flags": [
    {
      "label": "co je potenciální problém",
      "severity": 1-5,
      "source": "text_inzeratu | odhad_lokality | chybějící_informace",
      "comment": "krátké upřesnění"
    }
  ],
  "missing_critical_info": [
    {
      "label": "jaká důležitá informace chybí",
      "importance": 1-5,
      "comment": "proč je to důležité a co si ověřit"
    }
  ],
  "comparison": {
    "segment": "např. 2+kk, novostavba, Praha 9 – Kyje",
    "position": "spíš dražší | v normě | spíš levnější | neznámé",
    "comment": "subjektivní porovnání s typickým bytem v daném segmentu",
    "key_pros": [],
    "key_cons": []
  },
  "checklist_for_viewing": [
    "krátké body, na co si dát na prohlídce pozor"
  ]
}

Pokud nějaké číslo nemůžeš rozumně odhadnout, dej null a vysvětli to v comment.
Buď stručný, ale konkrétní a zaměř se na rizika, nedostatky a reálnou hodnotu pro nájemníka / kupujícího.
Pole "location", "locality" a text v "raw_text" (který už obsahuje i description) používej jako hlavní zdroj pro odhad lokality (ulice, městská část, město) a podle toho odvozuj typickou úroveň cen a atraktivitu.
"""


def _prepare_listing_for_ai(listing: Dict[str, Any]) -> Dict[str, Any]:
    """
    Sloučí description + raw_text do jednoho pole raw_text, aby měl model
    všechen text na jednom místě, a nic mu neuteklo.
    """
    desc = listing.get("description") or ""
    raw = listing.get("raw_text") or ""

    combined_parts = []
    if desc:
        combined_parts.append(str(desc))
    if raw:
        combined_parts.append(str(raw))

    combined_text = "\n\n".join(combined_parts) if combined_parts else ""

    listing_prepared = dict(listing)
    if combined_text:
        listing_prepared["raw_text"] = combined_text

    # Pro jistotu nic nemažeme – ostatní pole necháváme, jen doplňujeme raw_text.
    return listing_prepared


def call_chatgpt_for_listing(listing: Dict[str, Any]) -> Dict[str, Any]:
    """
    listing = dict se scrapnutými/parsnutými daty inzerátu.
    Vrátí dict s analýzou podle JSON schématu v SYSTEM_PROMPT.
    """
    listing_for_ai = _prepare_listing_for_ai(listing)

    user_payload = {
        "listing": listing_for_ai
    }

    resp = client.chat.completions.create(
        model="gpt-4.1-mini",  # pokud by tenhle model nešel, zkus "gpt-4o-mini"
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
        ],
        response_format={"type": "json_object"},
        temperature=0,
    )

    text = resp.choices[0].message.content

    # mělo by to být validní JSON díky response_format
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # nouzový fallback – vrátíme aspoň raw text
        return {
            "overall_comment": "Chyba při parsování JSON z AI.",
            "raw_output": text,
        }


def format_analysis_for_slack(analysis: Dict[str, Any], listing: Dict[str, Any]) -> str:
    """
    Převede JSON analýzy na hezký text, který pošleš v DM na Slacku.
    """
    lines = []

    url = listing.get("url", "")
    title = listing.get("title", "Inzerát")

    lines.append(f"*Analýza inzerátu:* <{url}|{title}>")
    lines.append("")

    # Shrnutí
    overall = analysis.get("overall_comment", "")
    if overall:
        lines.append(f"*Shrnutí:* {overall}")
        lines.append("")

    # Cena
    pa = analysis.get("price_assessment") or {}
    verdict = pa.get("verdict", "nelze_posoudit")
    confidence = pa.get("confidence", 0)
    lines.append(f"*Cena:* {verdict} (confidence {confidence}/5)")
    if pa.get("comment"):
        lines.append(f"_Komentář:_ {pa['comment']}")
    lines.append("")

    # Red flags – top 3 podle severity
    red_flags = analysis.get("red_flags") or []
    if red_flags:
        red_flags_sorted = sorted(red_flags, key=lambda x: -(x.get("severity") or 0))
        lines.append("*Red flags:*")
        for rf in red_flags_sorted[:3]:
            lines.append(
                f"• ({rf.get('severity', 0)}/5) *{rf.get('label', '')}* – {rf.get('comment', '')}"
            )
        lines.append("")

    # Chybějící zásadní informace – importance >= 3
    missing = analysis.get("missing_critical_info") or []
    missing_important = [m for m in missing if (m.get("importance") or 0) >= 3]
    if missing_important:
        lines.append("*Chybějící zásadní informace:*")
        for m in missing_important:
            lines.append(
                f"• ({m.get('importance', 0)}/5) *{m.get('label', '')}* – {m.get('comment', '')}"
            )
        lines.append("")

    # Checklist
    checklist = analysis.get("checklist_for_viewing") or []
    if checklist:
        lines.append("*Checklist na prohlídku:*")
        for item in checklist:
            lines.append(f"• {item}")

    return "\n".join(lines)