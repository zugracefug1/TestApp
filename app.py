import html
import json
import os
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

import streamlit as st

st.set_page_config(page_title="쇼핑 리스트", page_icon="🛒", layout="centered")

DATA_FILE = Path(__file__).parent / "data.json"
MAX_QUANTITY = 999
KST = timezone(timedelta(hours=9), "KST")  # 한국은 서머타임이 없어 고정 오프셋으로 충분


# ---------- 저장 / 불러오기 ----------
@st.cache_resource
def storage_lock() -> threading.Lock:
    """모든 세션이 공유하는 파일 잠금 (스크립트가 재실행돼도 같은 객체 유지)."""
    return threading.Lock()


def is_valid_item(item) -> bool:
    return (
        isinstance(item, dict)
        and isinstance(item.get("id"), str) and item["id"]
        and isinstance(item.get("name"), str) and item["name"].strip()
        and type(item.get("quantity")) is int and 1 <= item["quantity"] <= MAX_QUANTITY
        and isinstance(item.get("checked"), bool)
    )


def load_items() -> list[dict]:
    try:
        data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    items, seen = [], set()
    for item in data:
        if is_valid_item(item) and item["id"] not in seen:
            seen.add(item["id"])
            items.append(item)
    return items


def save_items(items: list[dict]) -> None:
    tmp = DATA_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, DATA_FILE)  # 쓰는 도중 중단돼도 기존 파일이 깨지지 않도록


@contextmanager
def edit_items():
    """파일에서 최신 목록을 읽어 수정한 뒤 저장한다. 다른 탭/사용자의 변경을 덮어쓰지 않기 위함."""
    with storage_lock():
        items = load_items()
        yield items
        save_items(items)
    st.session_state.shopping_items = items


# ---------- 상태 초기화 ----------
def init_state():
    st.session_state.shopping_items = load_items()
    if "editing_id" not in st.session_state:
        st.session_state.editing_id = None
    if "edit_error" not in st.session_state:
        st.session_state.edit_error = None


def new_item(name: str, quantity: int = 1) -> dict:
    return {
        "id": str(uuid.uuid4()),
        "name": name,
        "quantity": quantity,
        "checked": False,
        "created_at": datetime.now(KST).isoformat(timespec="seconds"),
    }


def find_item(items: list[dict], item_id: str) -> dict | None:
    return next((item for item in items if item["id"] == item_id), None)


# ---------- 기능 함수 ----------
def add_item(name: str, quantity: int = 1) -> None:
    with edit_items() as items:
        items.append(new_item(name.strip(), int(quantity)))


def update_item(item_id: str, name: str, quantity: int) -> None:
    with edit_items() as items:
        item = find_item(items, item_id)
        if item is not None:
            item["name"] = name.strip()
            item["quantity"] = int(quantity)


def delete_item(item_id: str) -> None:
    with edit_items() as items:
        items[:] = [item for item in items if item["id"] != item_id]
    if st.session_state.editing_id == item_id:
        st.session_state.editing_id = None


def toggle_item(item_id: str) -> None:
    with edit_items() as items:
        item = find_item(items, item_id)
        if item is not None:
            item["checked"] = st.session_state[f"chk_{item_id}"]


def clear_checked() -> None:
    with edit_items() as items:
        checked_ids = {item["id"] for item in items if item["checked"]}
        items[:] = [item for item in items if not item["checked"]]
    if st.session_state.editing_id in checked_ids:
        st.session_state.editing_id = None


# ---------- 편집 모드 콜백 ----------
def start_edit(item_id: str) -> None:
    item = find_item(load_items(), item_id)
    if item is None:
        return
    st.session_state[f"edit_name_{item_id}"] = item["name"]
    st.session_state[f"edit_qty_{item_id}"] = item["quantity"]
    st.session_state.editing_id = item_id
    st.session_state.edit_error = None


def validate(name: str, quantity) -> str | None:
    if not name.strip():
        return "아이템명을 입력해 주세요."
    if quantity is None or not 1 <= quantity <= MAX_QUANTITY:
        return f"수량은 1~{MAX_QUANTITY} 사이로 입력해 주세요."
    return None


def submit_add() -> None:
    name, quantity = st.session_state.new_name, st.session_state.new_qty
    error = validate(name, quantity)
    if error:
        st.session_state.add_error = error  # 입력값은 그대로 두어 다시 고칠 수 있게 한다
        return
    add_item(name, quantity)
    st.session_state.new_name = ""
    st.session_state.new_qty = 1


def save_edit(item_id: str) -> None:
    name = st.session_state[f"edit_name_{item_id}"]
    quantity = st.session_state[f"edit_qty_{item_id}"]
    error = validate(name, quantity)
    if error:
        st.session_state.edit_error = error
        return
    update_item(item_id, name, quantity)
    st.session_state.editing_id = None
    st.session_state.edit_error = None


def cancel_edit() -> None:
    st.session_state.editing_id = None
    st.session_state.edit_error = None


def item_label_html(item: dict) -> str:
    """아이템명을 HTML로 만든다.

    st.markdown은 서식 기호·URL 자동 링크·HTML 엔티티를 해석하므로,
    html.escape 후 st.html로 그려 사용자가 입력한 글자가 그대로 보이게 한다.
    """
    name = html.escape(item["name"])
    qty = f'<span style="opacity:.6;font-weight:400">× {item["quantity"]}</span>'
    if item["checked"]:
        return f'<span style="opacity:.5;text-decoration:line-through">{name}</span> {qty}'
    return f'<span style="font-weight:600">{name}</span> {qty}'


# ---------- 화면 ----------
WEEKDAYS = "월화수목금토일"
ICON_BUTTON_KEYS = ("add_btn", "edit_", "del_", "save_", "cancel_")

# 아이콘 버튼의 글자 라벨은 눈에는 숨기고 화면 낭독기에는 읽히게 한다 (sr-only)
st.html(
    "<style>"
    + ", ".join(f'[class*="st-key-{k}"] button [data-testid="stMarkdownContainer"]' for k in ICON_BUTTON_KEYS)
    + "{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}"
    + "</style>"
)

init_state()
items = st.session_state.shopping_items
done = sum(1 for item in items if item["checked"])
total = len(items)

# 헤더: 제목 + 날짜 + 진행 상황
today = datetime.now(KST)
st.title("🛒 쇼핑 리스트")
st.caption(f"{today.month}월 {today.day}일 ({WEEKDAYS[today.weekday()]}) · 오늘 살 물건을 정리해 보세요")

if total:
    st.progress(done / total, text=f"구매 완료 **{done}** / {total} · {done * 100 // total}%")
    if done == total:
        st.success("장보기 완료! 🎉")

# 입력 폼
# 수량 범위는 number_input의 min/max 대신 validate()에서 검사한다.
# (min/max를 걸면 범위 밖 값일 때 브라우저가 제출 자체를 막아 한국어 안내를 띄울 수 없다)
with st.form("add_form", border=True):
    with st.container(horizontal=True, vertical_alignment="bottom", gap="small", wrap=False):
        st.text_input("아이템명", placeholder="예: 우유", key="new_name")
        st.number_input("수량", value=1, step=1, width=110, key="new_qty")
        st.form_submit_button(
            "추가", icon=":material/add:", type="primary", help="추가",
            key="add_btn", on_click=submit_add,
        )

if error := st.session_state.pop("add_error", None):
    st.warning(error)

# 아이템 리스트: 미체크 → 체크 순 (정렬은 화면 표시용, 저장 순서는 그대로)
if not items:
    with st.container(border=True):
        st.markdown(
            "### 🧺\n**리스트가 비어 있어요**\n\n"
            ":gray[위 입력창에 살 물건을 적고 ＋ 버튼을 눌러 보세요.]",
            text_alignment="center",
        )

for item in sorted(items, key=lambda it: it["checked"]):
    item_id = item["id"]
    row_layout = dict(horizontal=True, vertical_alignment="center", gap="small", wrap=False)

    if st.session_state.editing_id == item_id:
        # 폼으로 감싸 입력칸에서 Enter를 누르면 저장되게 한다
        with st.form(f"edit_form_{item_id}", border=True), st.container(**row_layout):
            st.text_input(
                "아이템명", key=f"edit_name_{item_id}", placeholder="아이템명",
                label_visibility="collapsed",
            )
            st.number_input(
                "수량", step=1, key=f"edit_qty_{item_id}",
                label_visibility="collapsed", width=80,
            )
            st.form_submit_button(
                "저장", icon=":material/check:", key=f"save_{item_id}", help="저장",
                type="tertiary", on_click=save_edit, args=(item_id,),
            )
            st.form_submit_button(
                "취소", icon=":material/close:", key=f"cancel_{item_id}", help="취소",
                type="tertiary", on_click=cancel_edit,
            )
        if st.session_state.edit_error:
            st.error(st.session_state.edit_error)
        continue

    with st.container(border=True, **row_layout):
        # 다른 탭에서 바뀐 체크 상태가 반영되도록 매번 파일 값으로 맞춘다
        st.session_state[f"chk_{item_id}"] = item["checked"]
        st.checkbox(
            item["name"],  # 숨김 라벨이지만 접근성 이름(aria-label)으로 그대로 쓰인다
            key=f"chk_{item_id}",
            on_change=toggle_item,
            args=(item_id,),
            label_visibility="collapsed",
        )
        st.html(item_label_html(item), width="stretch")
        st.button(
            "수정", icon=":material/edit:", key=f"edit_{item_id}", help="수정",
            type="tertiary", on_click=start_edit, args=(item_id,),
        )
        st.button(
            "삭제", icon=":material/delete:", key=f"del_{item_id}", help="삭제",
            type="tertiary", on_click=delete_item, args=(item_id,),
        )

# 하단 버튼
if done:
    st.button(
        f"체크된 항목 {done}개 삭제", icon=":material/delete_sweep:",
        on_click=clear_checked, width="stretch",
    )
