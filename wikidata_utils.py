# wikidata_utils.py
from typing import List, Tuple, Dict, Optional
import requests
import time

USER_AGENT = "IE-HGT-Research/1.0 (your_email@example.com)"

WD_API = "https://www.wikidata.org/w/api.php"
session = requests.Session()
session.headers.update({"User-Agent": USER_AGENT})

def wd_search_qid(name: str, lang: str = "en") -> tuple[Optional[str], str, str]:
    """Trova il QID per un nome (label) con wbsearchentities (type=item)."""
    params = {
        "action": "wbsearchentities",
        "search": name, "language": lang,
        "format": "json", "type": "item", "limit": 1
    }
    r = session.get(WD_API, params=params, timeout=15)
    r.raise_for_status()
    js = r.json()
    if js.get("search"):
        it = js["search"][0]
        return it["id"], it.get("label",""), it.get("description","")
    return None, "", ""


def wd_get_label_desc(qid: str, lang: str = "en") -> tuple[str, str]:
    """Ritorna (label, description) per un QID; fallback a stringhe vuote."""
    params = {
        "action":"wbgetentities","ids":qid,"languages":lang,
        "props":"labels|descriptions","format":"json"
    }
    r = session.get(WD_API, params=params, timeout=15)
    r.raise_for_status()
    js = r.json().get("entities", {}).get(qid, {})
    lab = js.get("labels", {}).get(lang, {}).get("value", "")
    desc = js.get("descriptions", {}).get(lang, {}).get("value", "")
    return lab, desc


def wd_search_property_pid(label: str, lang: str = "en") -> Optional[str]:
    """Risolvi 'spouse' -> 'P26' (type=property)."""
    params = {
        "action": "wbsearchentities", "search": label,
        "language": lang, "format": "json", "type": "property", "limit": 1
    }
    r = session.get(WD_API, params=params, timeout=15)
    r.raise_for_status()
    js = r.json()
    if js.get("search"):
        return js["search"][0]["id"]
    return None


def resolve_property_keys(prop_keys: List[str], lang: str = "en") -> List[str]:
    """Accetta PIDs o label e restituisce sempre PIDs unici e ordinati."""
    if not prop_keys:
        return []
    out = []
    for k in prop_keys:
        k = k.strip()
        if not k:
            continue
        if k.upper().startswith("P") and k[1:].isdigit():
            out.append(k.upper())
        else:
            pid = wd_search_property_pid(k, lang=lang)
            if pid: out.append(pid)
    seen, uniq = set(), []
    for p in out:
        if p not in seen:
            seen.add(p); uniq.append(p)
    return uniq


def wd_get_claims(qid: str,
                  prop_keys: Optional[List[str]] = None,
                  lang: str = "en",
                  max_edges: int = 8,
                  preferred_only: bool = False) -> List[tuple[str, str, str]]:
    """
    Ritorna archi (qid, PID, tailQID).
    - prop_keys: []/None → nessuna whitelist: scorre tutte le property presenti
    - preferred_only: se True, prende solo claim rank 'preferred'
    - max_edges: cap per singolo QID (stop anticipato)
    """
    pids = resolve_property_keys(prop_keys or [], lang=lang)
    params = {"action": "wbgetclaims", "entity": qid, "format": "json"}
    r = session.get(WD_API, params=params, timeout=20)
    r.raise_for_status()
    claims = r.json().get("claims", {})

    edges: List[tuple[str, str, str]] = []
    prop_iter = (pids if pids else list(claims.keys()))

    for pid in prop_iter:
        for cl in claims.get(pid, []):
            if preferred_only and cl.get("rank","normal") != "preferred":
                continue
            snak = cl.get("mainsnak", {})
            dv = snak.get("datavalue", {})
            v = dv.get("value", {})
            if isinstance(v, dict) and v.get("id","").startswith("Q"):
                edges.append((qid, pid, v["id"]))
                if len(edges) >= max_edges:
                    return edges
    return edges


def expand_with_wikidata_qids(qids: List[str],
                              prop_keys: Optional[List[str]] = None,
                              prop_lang: str = "en",
                              max_edges_per_qid: int = 8,
                              preferred_only: bool = False,
                              sleep_s: float = 0.1) -> List[tuple[str, str, str]]:
    """Espande una lista di QID in archi (hQID, PID, tQID) con i filtri dati."""
    all_edges: List[tuple[str, str, str]] = []
    for q in qids:
        try:
            all_edges.extend(
                wd_get_claims(q, prop_keys=prop_keys, lang=prop_lang,
                              max_edges=max_edges_per_qid, preferred_only=preferred_only)
            )
        except Exception:
            pass
        time.sleep(sleep_s)
    return all_edges


def expand_multihop_wikidata(qids: List[str],
                              prop_keys: Optional[List[str]] = None,
                              prop_lang: str = "en",
                              max_edges_per_qid: int = 8,
                              preferred_only: bool = False,
                              sleep_s: float = 0.1,
                              max_hops: int = 2,
                              max_new_entities: int = 20) -> List[tuple[str, str, str]]:
    """
    Multi-hop Wikidata expansion (CRITICAL for multi-hop QA).

    Expands QIDs for multiple hops to discover intermediate entities.
    For question "What college did the President who attended Minneapolis High School go to?":
    - Hop 1: Minneapolis High School -> finds Hubert Humphrey (P69 educated at)
    - Hop 2: Hubert Humphrey -> finds University of Minnesota (P69 educated at)

    Args:
        qids: Initial QIDs to expand
        prop_keys: Property filters (e.g., ["educated at", "spouse"])
        prop_lang: Language for property resolution
        max_edges_per_qid: Max edges per entity
        preferred_only: Only use preferred rank claims
        sleep_s: Sleep between API calls
        max_hops: Number of expansion hops (default 2)
        max_new_entities: Max new entities to discover per hop

    Returns:
        All edges from all hops
    """
    all_edges: List[tuple[str, str, str]] = []
    visited_qids = set(qids)  # Avoid cycles
    current_frontier = list(qids)

    print(f"[MULTIHOP] Starting {max_hops}-hop expansion from {len(qids)} initial QIDs")

    for hop in range(max_hops):
        if not current_frontier:
            break

        print(f"[MULTIHOP] Hop {hop + 1}: Expanding {len(current_frontier)} QIDs...")

        hop_edges = []
        next_frontier = []

        for q in current_frontier:
            try:
                edges = wd_get_claims(
                    q, prop_keys=prop_keys, lang=prop_lang,
                    max_edges=max_edges_per_qid, preferred_only=preferred_only
                )
                hop_edges.extend(edges)

                # Collect new QIDs for next hop
                for _, _, tail_qid in edges:
                    if tail_qid not in visited_qids:
                        next_frontier.append(tail_qid)
                        visited_qids.add(tail_qid)

            except Exception as e:
                print(f"[WARN] Failed to expand {q}: {e}")
                pass

            time.sleep(sleep_s)

        all_edges.extend(hop_edges)
        print(f"[MULTIHOP] Hop {hop + 1}: Found {len(hop_edges)} edges, {len(next_frontier)} new entities")

        # Limit new entities to avoid explosion
        if len(next_frontier) > max_new_entities:
            print(f"[MULTIHOP] Limiting next frontier from {len(next_frontier)} to {max_new_entities}")
            next_frontier = next_frontier[:max_new_entities]

        current_frontier = next_frontier

    print(f"[MULTIHOP] Total: {len(all_edges)} edges across {max_hops} hops")
    return all_edges

# --- DYNAMIC: property label cache (no PID families) ---
_PID_LABEL_CACHE = {}

def wd_get_property_label(pid: str, lang: str = "en") -> str:
    """Ritorna la label testuale di una property PID; cache locale per non ripetere richieste."""
    global _PID_LABEL_CACHE
    if pid in _PID_LABEL_CACHE:
        return _PID_LABEL_CACHE[pid]

    # Use requests session with proper User-Agent header (not urllib)
    params = {
        "action": "wbgetentities",
        "ids": pid,
        "props": "labels",
        "languages": lang,
        "format": "json"
    }
    try:
        r = session.get(WD_API, params=params, timeout=15)
        r.raise_for_status()
        data = r.json()
        label = data.get("entities", {}).get(pid, {}).get("labels", {}).get(lang, {}).get("value", pid)
        _PID_LABEL_CACHE[pid] = label
        return label
    except Exception as e:
        print(f"[WARN] Failed to get property label for {pid}: {e}")
        _PID_LABEL_CACHE[pid] = pid  # Cache the PID itself as fallback
        return pid
