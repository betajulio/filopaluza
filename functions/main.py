import re
import json
import os
import unicodedata
from urllib.parse import quote_plus
from firebase_functions import scheduler_fn, https_fn
from firebase_admin import initialize_app, firestore
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
import pytz

initialize_app()

# ─── CONFIGURAÇÕES ──────────────────────────────────────────────────
SITE_URL = "https://betajulio.github.io/filopaluza/"
PROMOTION_ADMIN_TOKEN = "filopaluza-admin-token-TROQUE-ISSO"

try:
    SP_TZ = ZoneInfo("America/Sao_Paulo")
except ZoneInfoNotFoundError:
    SP_TZ = pytz.timezone("America/Sao_Paulo")

def now_sp():
    return datetime.now(SP_TZ)

# ─── HELPERS DE DATA ────────────────────────────────────────────────
def get_next_promotion_datetime(reference=None):
    ref = reference.astimezone(SP_TZ) if isinstance(reference, datetime) else now_sp()
    date = ref.replace(second=0, microsecond=0)
    day_of_week = date.weekday()
    days_until_friday = (4 - day_of_week + 7) % 7
    is_friday_after_cutoff = day_of_week == 4 and (
        date.hour > 23 or (date.hour == 23 and date.minute >= 59)
    )
    if days_until_friday == 0 and is_friday_after_cutoff:
        days_until_friday = 7
    target = date + timedelta(days=days_until_friday)
    return target.replace(hour=23, minute=59, second=0, microsecond=0)

def to_datetime(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if hasattr(value, "to_datetime"):
        return value.to_datetime()
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None

def slugify_text(value):
    normalized = unicodedata.normalize("NFKD", value or "")
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", ascii_text.lower()).strip("-")
    return slug

def json_response(payload, status=200):
    resp = https_fn.Response(
        response=json.dumps(payload, ensure_ascii=False, default=str),
        status=status,
        mimetype="application/json",
    )
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type,x-admin-token"
    return resp

# ─── PROMOTION STATE ────────────────────────────────────────────────
def promotion_state_ref(db):
    return db.collection("promotion_state").document("current")

def ensure_promotion_state(db):
    ref = promotion_state_ref(db)
    snap = ref.get()
    if snap.exists:
        return snap
    ref.set({
        "nextPromotionDate": get_next_promotion_datetime(),
        "activeTiebreakerPoll": None,
        "activeRepertoryPoll": None,
        "pendingRepertorySuggestionId": None,
        "completionLockToken": None,
        "completionLockUntil": None,
        "completionLockPollId": None,
        "promotionLockToken": None,
        "promotionLockUntil": None,
        "promotionPaused": False,
        "promotionPausedAt": None,
        "promotionResumedAt": None,
    })
    return ref.get()

def get_poll_snapshot_data(db, poll_id):
    if not poll_id:
        return None, False
    snap = db.collection("polls").document(str(poll_id)).get()
    return snap, snap.exists

def is_poll_closed_or_due(poll_data):
    if not poll_data:
        return False
    if poll_data.get("closed") is True:
        return True
    deadline = to_datetime(poll_data.get("deadline"))
    return bool(deadline and now_sp().astimezone(deadline.tzinfo or SP_TZ) >= deadline)

def normalize_promotion_state(db):
    state_snap = ensure_promotion_state(db)
    state = state_snap.to_dict() or {}
    updates = {}
    if "promotionPaused" not in state:
        updates["promotionPaused"] = False
    active_tiebreaker = state.get("activeTiebreakerPoll")
    _, tie_exists = get_poll_snapshot_data(db, active_tiebreaker)
    if active_tiebreaker and not tie_exists:
        updates["activeTiebreakerPoll"] = None
    active_repertory = state.get("activeRepertoryPoll")
    rep_snap, rep_exists = get_poll_snapshot_data(db, active_repertory)
    if active_repertory and not rep_exists:
        updates["activeRepertoryPoll"] = None
    elif active_repertory and rep_exists:
        rep_data = rep_snap.to_dict() or {}
        if rep_data.get("closed") is True:
            updates["activeRepertoryPoll"] = None
    pending_repertory = state.get("pendingRepertorySuggestionId")
    if pending_repertory:
        pending_snap = db.collection("suggestions").document(str(pending_repertory)).get()
        if not pending_snap.exists:
            updates["pendingRepertorySuggestionId"] = None
    if updates:
        promotion_state_ref(db).set(updates, merge=True)
        state.update(updates)
    return state

def inspect_promotion_state(db):
    state = normalize_promotion_state(db)
    tiebreaker_id = state.get("activeTiebreakerPoll")
    repertory_id = state.get("activeRepertoryPoll")
    tie_snap, tie_exists = get_poll_snapshot_data(db, tiebreaker_id)
    rep_snap, rep_exists = get_poll_snapshot_data(db, repertory_id)
    return {
        "ok": True,
        "state": state,
        "activeTiebreakerPoll": {
            "id": tiebreaker_id,
            "exists": tie_exists,
            "data": tie_snap.to_dict() if tie_exists else None
        },
        "activeRepertoryPoll": {
            "id": repertory_id,
            "exists": rep_exists,
            "data": rep_snap.to_dict() if rep_exists else None
        }
    }

def set_promotion_pause(db, paused):
    state_ref = promotion_state_ref(db)
    updates = {"promotionPaused": bool(paused)}
    if paused:
        updates["promotionPausedAt"] = firestore.SERVER_TIMESTAMP
    else:
        updates["promotionResumedAt"] = firestore.SERVER_TIMESTAMP
    state_ref.set(updates, merge=True)
    return inspect_promotion_state(db)

# ─── SUGGESTIONS ────────────────────────────────────────────────────
def get_suggestion_score(data):
    return int((data or {}).get("likes", 0) or 0) - int((data or {}).get("dislikes", 0) or 0)

def get_sorted_suggestions(db):
    def sort_key(doc):
        data = doc.to_dict() or {}
        created_at = to_datetime(data.get("createdAt"))
        created_ts = created_at.timestamp() if isinstance(created_at, datetime) else 0
        return (get_suggestion_score(data), int(data.get("likes", 0) or 0), created_ts)
    suggestions = list(db.collection("suggestions").stream())
    return sorted(suggestions, key=sort_key, reverse=True)

def get_top_tied_suggestions(db, limit=3):
    sorted_suggestions = get_sorted_suggestions(db)
    if not sorted_suggestions:
        return []
    top_score = get_suggestion_score(sorted_suggestions[0].to_dict() or {})
    top_candidates = [doc for doc in sorted_suggestions if get_suggestion_score(doc.to_dict() or {}) == top_score]
    return top_candidates[:min(limit, len(top_candidates))]

# ─── POLLS ──────────────────────────────────────────────────────────
def create_tiebreaker_poll_backend(db, suggestion_docs):
    end_date = now_sp() + timedelta(hours=48)
    poll_ref = db.collection("polls").document()
    poll_ref.set({
        "question": "🤠 Desempate: Qual música deve ir para a enquete de repertório?",
        "options": [
            {
                "label": f"{(doc.to_dict() or {}).get('song', 'Música')} - {(doc.to_dict() or {}).get('artist', 'Artista')}",
                "votes": 0
            }
            for doc in suggestion_docs
        ],
        "createdAt": firestore.SERVER_TIMESTAMP,
        "deadline": end_date.astimezone(ZoneInfo("UTC")).isoformat(),
        "closed": False,
        "voters": [],
        "voterMap": {},
        "suggestionIds": [doc.id for doc in suggestion_docs],
        "type": "tiebreaker"
    })
    return poll_ref.id

def create_repertory_poll_backend(db, suggestion_doc):
    data = suggestion_doc.to_dict() or {}
    end_date = now_sp() + timedelta(days=7)
    poll_ref = db.collection("polls").document()
    poll_ref.set({
        "question": f"🎵 {data.get('song', 'Música')} - {data.get('artist', 'Artista')} deve entrar no repertório?",
        "options": [
            {"label": "✅ Sim, adicionar ao repertório", "votes": 0},
            {"label": "❌ Não, manter em sugestões", "votes": 0}
        ],
        "createdAt": firestore.SERVER_TIMESTAMP,
        "deadline": end_date.astimezone(ZoneInfo("UTC")).isoformat(),
        "closed": False,
        "voters": [],
        "voterMap": {},
        "suggestionId": suggestion_doc.id,
        "type": "repertory"
    })
    suggestion_doc.reference.delete()
    return poll_ref.id

def extract_repertory_poll_song(poll):
    title = re.search(r"🎵\s*(.+?)\s*deve entrar", poll.get("question", "") or "")
    return title.group(1).strip() if title else "Música"

def apply_repertory_poll_result(db, poll):
    options = poll.get("options", []) or []
    yes_votes = options[0].get("votes", 0) if len(options) > 0 else 0
    no_votes = options[1].get("votes", 0) if len(options) > 1 else 0
    song_and_artist = extract_repertory_poll_song(poll)
    song_title, artist = (song_and_artist.split(" - ", 1) + [""])[:2]
    if yes_votes > no_votes:
        db.collection("repertorio").document().set({
            "song": song_title.strip(),
            "artist": artist.strip(),
            "addedAt": firestore.SERVER_TIMESTAMP,
            "by": "Sistema Automático"
        })
        return "approved"
    db.collection("suggestions").document().set({
        "song": song_title.strip(),
        "artist": artist.strip(),
        "by": "Sistema",
        "createdAt": firestore.SERVER_TIMESTAMP,
        "likes": 0,
        "dislikes": 0,
        "voterMap": {}
    })
    return "rejected"

def get_poll_option_label(option):
    return str((option or {}).get("label") or (option or {}).get("text") or "").strip()

def get_tiebreaker_label_from_suggestion(db, poll, option_index):
    suggestion_ids = poll.get("suggestionIds", []) or []
    if option_index < 0 or option_index >= len(suggestion_ids):
        return ""
    suggestion_snap = db.collection("suggestions").document(str(suggestion_ids[option_index])).get()
    if not suggestion_snap.exists:
        return ""
    data = suggestion_snap.to_dict() or {}
    song = str(data.get("song") or "").strip()
    artist = str(data.get("artist") or "").strip()
    return f"{song} - {artist}" if song and artist else (song or artist)

def activate_or_queue_repertory_poll(db, suggestion_doc):
    state = normalize_promotion_state(db)
    state_ref = promotion_state_ref(db)
    active_repertory = state.get("activeRepertoryPoll")
    if active_repertory:
        rep_snap, rep_exists = get_poll_snapshot_data(db, active_repertory)
        rep_data = rep_snap.to_dict() if rep_exists else None
        if (not rep_exists) or is_poll_closed_or_due(rep_data):
            process_repertory_completion(db)
            state = normalize_promotion_state(db)
            active_repertory = state.get("activeRepertoryPoll")
    poll_id = create_repertory_poll_backend(db, suggestion_doc)
    updates = {"pendingRepertorySuggestionId": None}
    if not active_repertory:
        updates["activeRepertoryPoll"] = poll_id
    state_ref.set(updates, merge=True)
    return {"status": "created", "pollId": poll_id, "suggestionId": suggestion_doc.id}

def process_pending_repertory_poll(db):
    state = normalize_promotion_state(db)
    pending_suggestion_id = state.get("pendingRepertorySuggestionId")
    if not pending_suggestion_id:
        return None
    state_ref = promotion_state_ref(db)
    pending_ref = db.collection("suggestions").document(str(pending_suggestion_id))
    pending_snap = pending_ref.get()
    if not pending_snap.exists:
        state_ref.set({"pendingRepertorySuggestionId": None}, merge=True)
        return {"status": "cleared_missing", "suggestionId": str(pending_suggestion_id)}
    poll_id = create_repertory_poll_backend(db, pending_snap)
    updates = {"pendingRepertorySuggestionId": None}
    if not state.get("activeRepertoryPoll"):
        updates["activeRepertoryPoll"] = poll_id
    state_ref.set(updates, merge=True)
    return {"status": "created", "pollId": poll_id, "suggestionId": str(pending_suggestion_id)}

def process_due_repertory_polls(db):
    completed = []
    for poll_doc in db.collection("polls").where("type", "==", "repertory").where("closed", "==", False).stream():
        poll = poll_doc.to_dict() or {}
        deadline = to_datetime(poll.get("deadline"))
        if poll.get("closed") is True or not deadline or now_sp().astimezone(deadline.tzinfo or SP_TZ) < deadline:
            continue
        poll_doc.reference.set({"closed": True}, merge=True)
        result = apply_repertory_poll_result(db, poll)
        completed.append({"pollId": poll_doc.id, "result": result})
    if not completed:
        return []
    state = normalize_promotion_state(db)
    active_repertory = state.get("activeRepertoryPoll")
    if active_repertory and any(item["pollId"] == active_repertory for item in completed):
        promotion_state_ref(db).set({
            "activeRepertoryPoll": None,
            "nextPromotionDate": get_next_promotion_datetime()
        }, merge=True)
    return completed

def process_repertory_completion(db):
    state = normalize_promotion_state(db)
    poll_id = state.get("activeRepertoryPoll")
    if not poll_id:
        return
    state_ref = promotion_state_ref(db)
    poll_ref = db.collection("polls").document(poll_id)
    poll_snap = poll_ref.get()
    if not poll_snap.exists:
        state_ref.set({"activeRepertoryPoll": None, "nextPromotionDate": get_next_promotion_datetime()}, merge=True)
        return
    poll = poll_snap.to_dict() or {}
    deadline = to_datetime(poll.get("deadline"))
    if poll.get("closed") is True or not deadline or now_sp().astimezone(deadline.tzinfo or SP_TZ) < deadline:
        return
    poll_ref.set({"closed": True}, merge=True)
    apply_repertory_poll_result(db, poll)
    pending_suggestion_id = state.get("pendingRepertorySuggestionId")
    if pending_suggestion_id:
        pending_ref = db.collection("suggestions").document(str(pending_suggestion_id))
        pending_snap = pending_ref.get()
        if pending_snap.exists:
            state_ref.set({"activeRepertoryPoll": None}, merge=True)
            queued_result = activate_or_queue_repertory_poll(db, pending_snap)
            state_ref.set({
                "activeRepertoryPoll": queued_result.get("pollId"),
                "pendingRepertorySuggestionId": None,
                "nextPromotionDate": get_next_promotion_datetime()
            }, merge=True)
            return
        state_ref.set({"pendingRepertorySuggestionId": None}, merge=True)
    state_ref.set({"activeRepertoryPoll": None, "nextPromotionDate": get_next_promotion_datetime()}, merge=True)

def process_tiebreaker_completion(db):
    state = normalize_promotion_state(db)
    poll_id = state.get("activeTiebreakerPoll")
    if not poll_id:
        return
    state_ref = promotion_state_ref(db)
    poll_ref = db.collection("polls").document(poll_id)
    poll_snap = poll_ref.get()
    if not poll_snap.exists:
        state_ref.set({"activeTiebreakerPoll": None}, merge=True)
        return
    poll = poll_snap.to_dict() or {}
    deadline = to_datetime(poll.get("deadline"))
    if poll.get("closed") is True or not deadline or now_sp().astimezone(deadline.tzinfo or SP_TZ) < deadline:
        return
    options = poll.get("options", []) or []
    if not options:
        poll_ref.set({"closed": True}, merge=True)
        state_ref.set({"activeTiebreakerPoll": None, "nextPromotionDate": get_next_promotion_datetime()}, merge=True)
        return
    max_votes = max((opt.get("votes", 0) or 0) for opt in options)
    winner_idx = next((idx for idx, opt in enumerate(options) if (opt.get("votes", 0) or 0) == max_votes), None)
    suggestion_ids = poll.get("suggestionIds", []) or []
    if winner_idx is None or winner_idx >= len(suggestion_ids):
        poll_ref.set({"closed": True}, merge=True)
        state_ref.set({"activeTiebreakerPoll": None, "nextPromotionDate": get_next_promotion_datetime()}, merge=True)
        return
    suggestion_ref = db.collection("suggestions").document(suggestion_ids[winner_idx])
    suggestion_snap = suggestion_ref.get()
    winner_label = get_poll_option_label(options[winner_idx]) or (
        f"{(suggestion_snap.to_dict() or {}).get('song', '')} - {(suggestion_snap.to_dict() or {}).get('artist', '')}".strip(" -")
        if suggestion_snap.exists else ""
    )
    poll_ref.set({"closed": True, "winnerLabel": winner_label}, merge=True)
    if not suggestion_snap.exists:
        state_ref.set({"activeTiebreakerPoll": None, "nextPromotionDate": get_next_promotion_datetime()}, merge=True)
        return
    repertory_result = activate_or_queue_repertory_poll(db, suggestion_snap)
    if repertory_result["status"] == "created":
        state_ref.set({"activeTiebreakerPoll": None}, merge=True)
        return
    state_ref.set({
        "activeTiebreakerPoll": None,
        "pendingRepertorySuggestionId": suggestion_snap.id
    }, merge=True)

def process_due_promotion(db):
    state = normalize_promotion_state(db)
    state_ref = promotion_state_ref(db)
    now_local = now_sp()
    next_promotion = to_datetime(state.get("nextPromotionDate"))
    if state.get("promotionPaused") is True:
        return
    if next_promotion and next_promotion.astimezone(SP_TZ) > now_local:
        return
    if state.get("pendingRepertorySuggestionId"):
        process_pending_repertory_poll(db)
        return
    if state.get("activeTiebreakerPoll") or state.get("pendingRepertorySuggestionId"):
        return
    suggestions = list(db.collection("suggestions").stream())
    if not suggestions:
        state_ref.set({"nextPromotionDate": get_next_promotion_datetime(now_local)}, merge=True)
        return
    sorted_suggestions = sorted(
        suggestions,
        key=lambda doc: (
            get_suggestion_score(doc.to_dict() or {}),
            int((doc.to_dict() or {}).get("likes", 0) or 0)
        ),
        reverse=True
    )
    top_score = get_suggestion_score(sorted_suggestions[0].to_dict() or {})
    top_candidates = [doc for doc in sorted_suggestions if get_suggestion_score(doc.to_dict() or {}) == top_score]
    if len(top_candidates) >= 2:
        poll_id = create_tiebreaker_poll_backend(db, top_candidates[:min(3, len(top_candidates))])
        state_ref.set({
            "activeTiebreakerPoll": poll_id,
            "nextPromotionDate": get_next_promotion_datetime(now_local)
        }, merge=True)
        return
    repertory_result = activate_or_queue_repertory_poll(db, top_candidates[0])
    state_ref.set({"nextPromotionDate": get_next_promotion_datetime(now_local)}, merge=True)

def advance_promotion_pipeline(db):
    completed_repertory_polls = process_due_repertory_polls(db)
    process_repertory_completion(db)
    pending_before_tie = process_pending_repertory_poll(db)
    process_tiebreaker_completion(db)
    pending_after_tie = process_pending_repertory_poll(db)
    process_due_promotion(db)
    return {
        "ok": True,
        "completedRepertoryPolls": completed_repertory_polls,
        "pendingBeforeTiebreaker": pending_before_tie,
        "pendingAfterTiebreaker": pending_after_tie,
        "state": normalize_promotion_state(db)
    }

def force_create_top3_tiebreaker(db):
    state = normalize_promotion_state(db)
    state_ref = promotion_state_ref(db)
    if state.get("activeTiebreakerPoll") or state.get("pendingRepertorySuggestionId"):
        return {
            "ok": False,
            "error": "Já existe um desempate ativo ou uma enquete de repertório pendente.",
            "activeTiebreakerPoll": state.get("activeTiebreakerPoll"),
        }
    selected = get_top_tied_suggestions(db, 3)
    if len(selected) < 2:
        return {"ok": False, "error": "Menos de duas sugestões disponíveis para desempate."}
    poll_id = create_tiebreaker_poll_backend(db, selected)
    state_ref.set({"activeTiebreakerPoll": poll_id}, merge=True)
    return {
        "ok": True,
        "pollId": poll_id,
        "songs": [
            {
                "id": doc.id,
                "song": (doc.to_dict() or {}).get("song", ""),
                "artist": (doc.to_dict() or {}).get("artist", ""),
                "score": get_suggestion_score(doc.to_dict() or {}),
            }
            for doc in selected
        ]
    }

def refresh_active_tiebreaker_from_ties(db):
    state = normalize_promotion_state(db)
    poll_id = state.get("activeTiebreakerPoll")
    if not poll_id:
        return {"ok": False, "error": "Nenhuma enquete de desempate ativa."}
    poll_ref = db.collection("polls").document(str(poll_id))
    poll_snap = poll_ref.get()
    if not poll_snap.exists:
        promotion_state_ref(db).set({"activeTiebreakerPoll": None}, merge=True)
        return {"ok": False, "error": "A enquete de desempate ativa não foi encontrada."}
    poll = poll_snap.to_dict() or {}
    options = poll.get("options", []) or []
    total_votes = sum(int((opt or {}).get("votes", 0) or 0) for opt in options)
    if total_votes > 0:
        return {"ok": False, "error": "A enquete já possui votos e não pode ser reordenada."}
    selected = get_top_tied_suggestions(db, 3)
    if len(selected) < 2:
        return {"ok": False, "error": "Não há sugestões empatadas suficientes."}
    new_options = [
        {"label": f"{(doc.to_dict() or {}).get('song', 'Música')} - {(doc.to_dict() or {}).get('artist', 'Artista')}", "votes": 0}
        for doc in selected
    ]
    poll_ref.set({"options": new_options, "suggestionIds": [doc.id for doc in selected]}, merge=True)
    return {"ok": True, "pollId": poll_id}

# ─── YOUTUBE / CIFRA ────────────────────────────────────────────────
def extract_youtube_id(url):
    regex = r'(?:youtube\.com\/(?:[^\/]+\/.+\/|(?:v|e(?:mbed)?)\/?|.*[?&]v=)|youtu\.be\/|youtube\.com\/shorts\/)([a-zA-Z0-9_-]{11})'
    match = re.search(regex, url)
    return match.group(1) if match else None

def extract_first_youtube_url(song, artist):
    import requests
    queries = [
        f"{song} {artist} oficial áudio".strip(),
        f"{song} {artist}".strip(),
    ]
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    }
    for query in queries:
        try:
            response = requests.get(
                "https://www.youtube.com/results",
                params={"search_query": query},
                headers=headers,
                timeout=15,
            )
            ids = re.findall(r'"videoId":"([A-Za-z0-9_-]{11})"', response.text)
            seen = []
            for video_id in ids:
                if video_id not in seen:
                    seen.append(video_id)
            if seen:
                return f"https://www.youtube.com/watch?v={seen[0]}"
        except Exception:
            pass
    return None

def build_cifra_candidates(song, artist):
    song_slug = slugify_text(song)
    artist_slug = slugify_text(artist)
    base_song_url = f"https://www.cifraclub.com.br/{artist_slug}/{song_slug}/" if artist_slug and song_slug else ""
    candidates = []
    if base_song_url:
        candidates.append({"label": "Cifra Club principal", "url": base_song_url})
        candidates.append({"label": "Cifra simplificada", "url": f"{base_song_url}simplificada.html"})
    if artist_slug:
        candidates.append({"label": "Artista no Cifra Club", "url": f"https://www.cifraclub.com.br/{artist_slug}/"})
    search_term = quote_plus(f"{song} {artist} cifra sertanejo")
    candidates.append({"label": "Busca Google por cifra", "url": f"https://www.google.com/search?q={search_term}"})
    return candidates

# ─── HTTP ENDPOINTS ─────────────────────────────────────────────────
@https_fn.on_request()
def lookup_youtube_link(req: https_fn.Request) -> https_fn.Response:
    if req.method == "OPTIONS":
        return json_response({}, 204)
    if req.method != "GET":
        return json_response({"ok": False, "error": "Método não suportado"}, 405)
    song = (req.args.get("song") or "").strip()
    artist = (req.args.get("artist") or "").strip()
    if not song:
        return json_response({"ok": False, "error": "Parâmetro song é obrigatório"}, 400)
    try:
        url = extract_first_youtube_url(song, artist)
    except Exception as exc:
        return json_response({"ok": False, "error": f"Falha ao buscar vídeo: {exc}"}, 500)
    if not url:
        return json_response({"ok": False, "error": "Nenhum vídeo encontrado"}, 404)
    return json_response({"ok": True, "url": url})

@https_fn.on_request()
def lookup_cifra_candidates(req: https_fn.Request) -> https_fn.Response:
    if req.method == "OPTIONS":
        return json_response({}, 204)
    if req.method != "GET":
        return json_response({"ok": False, "error": "Método não suportado"}, 405)
    song = (req.args.get("song") or "").strip()
    artist = (req.args.get("artist") or "").strip()
    if not song:
        return json_response({"ok": False, "error": "Parâmetro song é obrigatório"}, 400)
    candidates = build_cifra_candidates(song, artist)
    return json_response({"ok": True, "candidates": candidates})

@https_fn.on_request()
def admin_advance_promotion(req: https_fn.Request) -> https_fn.Response:
    if req.method == "OPTIONS":
        return json_response({}, 204)
    token = (req.args.get("token") or req.headers.get("x-admin-token") or "").strip()
    if token != PROMOTION_ADMIN_TOKEN:
        return json_response({"ok": False, "error": "unauthorized"}, 403)
    db = firestore.client()
    try:
        result = advance_promotion_pipeline(db)
        return json_response(result, 200)
    except Exception as exc:
        return json_response({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, 500)

@https_fn.on_request()
def admin_force_tiebreaker_top3(req: https_fn.Request) -> https_fn.Response:
    if req.method == "OPTIONS":
        return json_response({}, 204)
    token = (req.args.get("token") or req.headers.get("x-admin-token") or "").strip()
    if token != PROMOTION_ADMIN_TOKEN:
        return json_response({"ok": False, "error": "unauthorized"}, 403)
    db = firestore.client()
    try:
        result = force_create_top3_tiebreaker(db)
        return json_response(result, 200 if result.get("ok") else 409)
    except Exception as exc:
        return json_response({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, 500)

@https_fn.on_request()
def admin_inspect_promotion(req: https_fn.Request) -> https_fn.Response:
    if req.method == "OPTIONS":
        return json_response({}, 204)
    token = (req.args.get("token") or req.headers.get("x-admin-token") or "").strip()
    if token != PROMOTION_ADMIN_TOKEN:
        return json_response({"ok": False, "error": "unauthorized"}, 403)
    db = firestore.client()
    try:
        result = inspect_promotion_state(db)
        return json_response(result, 200)
    except Exception as exc:
        return json_response({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, 500)

@https_fn.on_request()
def admin_set_promotion_pause(req: https_fn.Request) -> https_fn.Response:
    if req.method == "OPTIONS":
        return json_response({}, 204)
    token = (req.args.get("token") or req.headers.get("x-admin-token") or "").strip()
    if token != PROMOTION_ADMIN_TOKEN:
        return json_response({"ok": False, "error": "unauthorized"}, 403)
    raw_paused = (req.args.get("paused") or "").strip().lower()
    if raw_paused not in ("true", "false", "1", "0", "yes", "no"):
        return json_response({"ok": False, "error": "Parâmetro paused deve ser true ou false."}, 400)
    db = firestore.client()
    try:
        result = set_promotion_pause(db, raw_paused in ("true", "1", "yes"))
        return json_response(result, 200)
    except Exception as exc:
        return json_response({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, 500)

@https_fn.on_request()
def admin_refresh_active_tiebreaker(req: https_fn.Request) -> https_fn.Response:
    if req.method == "OPTIONS":
        return json_response({}, 204)
    token = (req.args.get("token") or req.headers.get("x-admin-token") or "").strip()
    if token != PROMOTION_ADMIN_TOKEN:
        return json_response({"ok": False, "error": "unauthorized"}, 403)
    db = firestore.client()
    try:
        result = refresh_active_tiebreaker_from_ties(db)
        return json_response(result, 200 if result.get("ok") else 409)
    except Exception as exc:
        return json_response({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, 500)

# ─── AGENDAMENTO: MONITOR DE ENQUETES (A CADA 1 HORA) ────────────────
@scheduler_fn.on_schedule(schedule="0 * * * *", timezone="America/Sao_Paulo")
def poll_monitor(event: scheduler_fn.ScheduledEvent) -> None:
    db = firestore.client()
    try:
        advance_promotion_pipeline(db)
    except Exception as exc:
        print(f"Erro no pipeline automático de promoção: {type(exc).__name__}: {exc}")
