import requests
import re
import os
import io
import json
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime
import streamlit as st

# ================= 1. 配置管理与初始化 =================
DEFAULT_CONFIG = {
    "SEARCH_MAX": 15,
    "SAVE_AS_ASS": True,
    "ASS_FONT": "Microsoft YaHei",
    "NAME_FORMAT": "[标题][集数]",
    "ASS_FONT_BOLD": True,
    "ASS_FONT_SIZE": 50,
    "ASS_DURATION": 25,
    "ASS_DISPLAY_AREA": 0.2,
    "STOP_DURATION": 5,
    "ASS_OPACITY": 0.8,
    "ASS_OUTLINE": 1,
    "BASE_URL": "https://dan-mu-api.netlify.app/87654321",
}

CACHE_FILE = "config_cache.json"

def load_local_config():
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                return {**DEFAULT_CONFIG, **json.load(f)}
        except: return DEFAULT_CONFIG
    return DEFAULT_CONFIG

def save_local_config(config_dict):
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(config_dict, f, ensure_ascii=False, indent=4)

if "init" not in st.session_state:
    saved_conf = load_local_config()
    for k, v in saved_conf.items():
        st.session_state[f"cfg_{k}"] = v
    st.session_state.init = True

def add_format_tag(tag):
    st.session_state["cfg_NAME_FORMAT"] += tag

def clear_format():
    st.session_state["cfg_NAME_FORMAT"] = ""

CONFIG = {k: st.session_state[f"cfg_{k}"] for k in DEFAULT_CONFIG.keys()}

def reset_config_callback():
    for k, v in DEFAULT_CONFIG.items():
        st.session_state[f"cfg_{k}"] = v
    save_local_config(DEFAULT_CONFIG)

# ================= 2. 核心转换算法 =================
def get_ass_opacity_hex(opacity_pct):
    try: alpha = int(255 * (1 - max(0.0, min(1.0, opacity_pct)))); return f"{alpha:02x}"
    except: return "00"

def dec_to_ass_color(dec_color):
    try:
        hex_color = f"{int(dec_color):06x}"
        r, g, b = hex_color[0:2], hex_color[2:4], hex_color[4:6]
        return f"&H{get_ass_opacity_hex(CONFIG['ASS_OPACITY'])}{b}{g}{r}"
    except: return f"&H{get_ass_opacity_hex(CONFIG['ASS_OPACITY'])}FFFFFF"

def convert_xml_to_ass(xml_content):
    PLAY_RES_X, PLAY_RES_Y = 1920, 1080
    header = ["[Script Info]", "ScriptType: v4.00+", f"PlayResX: {PLAY_RES_X}", f"PlayResY: {PLAY_RES_Y}", "", "[V4+ Styles]", "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding", f"Style: Default,{CONFIG['ASS_FONT']},{CONFIG['ASS_FONT_SIZE']},&H{get_ass_opacity_hex(CONFIG['ASS_OPACITY'])}FFFFFF,&H00FFFFFF,&H00000000,&H00000000,{1 if CONFIG['ASS_FONT_BOLD'] else 0},0,0,0,100,100,0,0,1,{CONFIG['ASS_OUTLINE']},0,7,10,10,10,1", "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"]
    try:
        xml_content = re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F]', '', xml_content)
        root = ET.fromstring(xml_content.encode('utf-8'))
        display_h = int(PLAY_RES_Y * CONFIG['ASS_DISPLAY_AREA'])
        rows_scroll, rows_top = [None]*(display_h+1), [None]*(display_h+1)
        def format_time(t):
            t = max(0, t); return f"{int(t//3600)}:{int((t%3600)//60):02d}:{t%60:05.2f}"
        danmus = []
        for d in root.findall('d'):
            p = d.get('p').split(',')
            if len(p) >= 4:
                text = d.text if d.text else ""
                w = sum(2.0 if ord(c) > 127 else 1.0 for c in text) * (CONFIG['ASS_FONT_SIZE'] / 2)
                danmus.append({'start': float(p[0]), 'mode': int(p[1]), 'color': dec_to_ass_color(p[3]), 'text': text, 'w': w, 'h': int(CONFIG['ASS_FONT_SIZE'] * 1.2)})
        danmus.sort(key=lambda x: x['start'])
        events = []
        for c in danmus:
            m, start_t, w, h = c['mode'], c['start'], c['w'], c['h']
            target_row = -1
            if m in (1, 2, 3):
                threshold_t = start_t - CONFIG['ASS_DURATION'] * (1 - PLAY_RES_X / (w + PLAY_RES_X))
                for r in range(0, display_h - h, 8):
                    prev = rows_scroll[r]
                    if not prev or ((prev[0] + CONFIG['ASS_DURATION'] * (prev[1] / (prev[1] + PLAY_RES_X)) < start_t) and (prev[0] < threshold_t)):
                        target_row = r; break
                if target_row != -1:
                    for i in range(target_row, min(target_row + h, display_h)): rows_scroll[i] = (start_t, w)
                    y = target_row + CONFIG['ASS_FONT_SIZE']; move = f"\\move({PLAY_RES_X + 50},{y},{-w - 50},{y})"
                    events.append(f"Dialogue: 0,{format_time(start_t)},{format_time(start_t+CONFIG['ASS_DURATION'])},Default,,0,0,0,,{{{move}\\c{c['color']}}}{c['text']}")
            elif m == 5:
                for r in range(0, display_h - h, 8):
                    if not rows_top[r] or rows_top[r] < start_t: target_row = r; break
                if target_row != -1:
                    for i in range(target_row, min(target_row + h, display_h)): rows_top[i] = start_t + CONFIG['STOP_DURATION']
                    y = target_row + CONFIG['ASS_FONT_SIZE']
                    events.append(f"Dialogue: 1,{format_time(start_t)},{format_time(start_t+CONFIG['STOP_DURATION'])},Default,,0,0,0,,{{\\an8\\pos({PLAY_RES_X/2},{y})\\c{c['color']}}}{c['text']}")
        return "\n".join(header + events)
    except: return None

# ================= 3. UI 布局 =================
if "logs" not in st.session_state: st.session_state.logs = []
if "is_running" not in st.session_state: st.session_state.is_running = False
if "final_zip" not in st.session_state: st.session_state.final_zip = None
if "single_file" not in st.session_state: st.session_state.single_file = None
if "download_files" not in st.session_state: st.session_state.download_files = {}

def update_realtime_log(msg, placeholder=None):
    current_time = datetime.now().strftime("%H:%M:%S")
    st.session_state.logs.append(f"[{current_time}] {msg}")
    if placeholder:
        log_html = f'<div class="log-container" id="log-box">{"<br>".join(st.session_state.logs)}</div>'
        placeholder.markdown(log_html, unsafe_allow_html=True)

st.set_page_config(page_title="弹幕助手 Pro", page_icon="🎬", layout="centered")

st.markdown("""
    <style>
    .log-container { 
        height: 180px; overflow-y: auto; background-color: #1e1e1e; color: #00ff00; 
        border: 2px solid #444; border-radius: 8px; padding: 10px; 
        font-family: monospace; font-size: 12px; line-height: 1.4; margin-bottom: 10px; 
    }
    div[data-testid="stFormSubmitButton"] button {
        height: 45px; font-size: 18px !important; background-color: #ff4b4b !important; border-radius: 8px !important;
    }
    .stButton button { width: 100%; }
    </style>
""", unsafe_allow_html=True)

with st.sidebar:
    st.header("⚙️ 全局配置")
    c_btn1, c_btn2 = st.columns(2)
    with c_btn1:
        if st.button("💾 保存设置"):
            save_local_config(CONFIG); st.success("已保存")
    with c_btn2:
        st.button("🔄 重置设置", on_click=reset_config_callback)
    
    st.write("---")
    with st.expander("🎨 命名与样式", expanded=True):
        st.checkbox("保存为 ASS 格式", key="cfg_SAVE_AS_ASS")
        
        st.write("格式占位符：")
        tag_col1, tag_col2, tag_col3, tag_col4 = st.columns([1, 1, 1, 1.2])
        with tag_col1:
            st.button("[标题]", on_click=add_format_tag, args=("[标题]",), use_container_width=True)
        with tag_col2:
            st.button("[集数]", on_click=add_format_tag, args=("[集数]",), use_container_width=True)
        with tag_col3:
            st.button("[原]", on_click=add_format_tag, args=("[原]",), use_container_width=True)
        with tag_col4:
            st.button("🗑️ 清空", on_click=clear_format, use_container_width=True)
        
        st.text_input("文件命名格式", key="cfg_NAME_FORMAT")

        st.text_input("字体名称", key="cfg_ASS_FONT")
        st.slider("字体大小", 10, 100, key="cfg_ASS_FONT_SIZE")
        st.slider("不透明度", 0.0, 1.0, key="cfg_ASS_OPACITY")
        st.checkbox("加粗字体", key="cfg_ASS_FONT_BOLD")
        st.number_input("描边宽度", 0, 5, key="cfg_ASS_OUTLINE")
    with st.expander("⏱️ 时间与显示", expanded=True):
        st.number_input("滚动时长(秒)", 5, 60, key="cfg_ASS_DURATION")
        st.number_input("停留时长(秒)", 1, 20, key="cfg_STOP_DURATION")
        st.slider("显示区域占比", 0.1, 1.0, key="cfg_ASS_DISPLAY_AREA")
    with st.expander("🌐 网络与搜索", expanded=False):
        st.text_input("API 根地址", key="cfg_BASE_URL")
        st.number_input("搜索显示上限", 1, 50, key="cfg_SEARCH_MAX")

st.title("🎬 弹幕助手 Web Pro")

with st.form("search_form", clear_on_submit=False, border=False):
    col_main, col_btn = st.columns([4, 1], vertical_alignment="center")
    with col_main:
        keyword = st.text_input("🔍 搜索动漫名称", placeholder="输入关键词并回车...", label_visibility="collapsed", key="search_keyword")
    with col_btn:
        btn_search = st.form_submit_button("开始搜索")

has_eps = "current_animes" in st.session_state and st.session_state.current_animes

if has_eps:
    st.write("---")
    range_input = st.text_input("📥 下载范围 (0全部/1-5范围/序号)", value="0")

st.write("---")
st.subheader("🖥️ 执行状态与控制")
op_col1, op_col2, op_col3 = st.columns([1.5, 1.5, 1])

current_eps = []
is_movie_resource = False
if has_eps:
    anime_display_list = []
    anime_map = {}
    for i, a in enumerate(st.session_state.current_animes):
        first_ep_title = a['episodes'][0]['episodeTitle'] if a['episodes'] else ""
        type_tag_match = re.search(r'【(电影|动漫|其他)】', first_ep_title)
        type_tag = type_tag_match.group(0) if type_tag_match else ""
        plats = "".join(list(set(re.match(r'^([【\[].+?[\]】])', ep['episodeTitle']).group(1) if re.match(r'^([【\[].+?[\]】])', ep['episodeTitle']) else "【他】" for ep in a['episodes'])))
        d_str = f"[{i+1}] {a['animeTitle']} {type_tag} {plats}"
        anime_display_list.append(d_str)
        anime_map[d_str] = a

    selected_label = st.radio("选择资源：", anime_display_list)
    selected_anime = anime_map[selected_label]
    is_movie_resource = "【电影】" in selected_label
    
    platform_map = {}
    for ep in selected_anime['episodes']:
        p = (re.match(r'^([【\[].+?[\]】])', ep['episodeTitle']).group(1) if re.match(r'^([【\[].+?[\]】])', ep['episodeTitle']) else "【他】")
        if p not in platform_map: platform_map[p] = []
        platform_map[p].append(ep)
    
    p_choice = st.selectbox("选择来源平台", list(platform_map.keys()))
    current_eps = platform_map[p_choice]

    with st.expander(f"📖 剧集预览 (共 {len(current_eps)} 集)", expanded=False):
        st.markdown("  \n".join([f"**[{i+1}]** {ep['episodeTitle']}" for i, ep in enumerate(current_eps)]))

if has_eps:
    if not st.session_state.is_running:
        if op_col1.button("🚀 开始下载并打包", type="primary"):
            st.session_state.is_running = True
            st.session_state.download_files = {}
            st.session_state.final_zip = None
            st.session_state.single_file = None
            st.rerun()
    else:
        if op_col1.button("🛑 停止下载", type="secondary"):
            st.session_state.is_running = False
            st.rerun()

if not st.session_state.is_running and st.session_state.download_files:
    if len(st.session_state.download_files) == 1:
        fname = list(st.session_state.download_files.keys())[0]
        st.session_state.single_file = (fname, st.session_state.download_files[fname])
        st.session_state.final_zip = None
    else:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "a", zipfile.ZIP_DEFLATED) as zf:
            for fname, fdata in st.session_state.download_files.items():
                zf.writestr(fname, fdata)
        st.session_state.final_zip = buf.getvalue()
        st.session_state.single_file = None

if st.session_state.final_zip:
    op_col2.download_button(label=f"💾 保存弹幕包 ({len(st.session_state.download_files)}集)", data=st.session_state.final_zip, file_name=f"{keyword}_弹幕包.zip", mime="application/zip")
elif st.session_state.single_file:
    f_name, f_data = st.session_state.single_file
    op_col2.download_button(label=f"💾 保存弹幕文件", data=f_data, file_name=f_name, mime="text/plain")

if op_col3.button("🧹 清理"):
    st.session_state.logs = []; st.session_state.final_zip = None; st.session_state.single_file = None; st.session_state.download_files = {}; st.session_state.is_running = False; st.rerun()

log_area = st.empty()
log_area.markdown(f'<div class="log-container" id="log-box">{"<br>".join(st.session_state.logs) if st.session_state.logs else "等待任务启动..."}</div>', unsafe_allow_html=True)
st.components.v1.html("""<script>function sc(){var b=window.parent.document.getElementById('log-box');if(b)b.scrollTop=b.scrollHeight;}setInterval(sc,500);</script>""", height=0)

# ================= 4. 后台逻辑 =================
if btn_search and keyword:
    st.session_state.logs = [] 
    update_realtime_log(f"正在发起搜索: {keyword} ...", log_area)
    try:
        res = requests.get(f"{CONFIG['BASE_URL']}/api/v2/search/episodes", params={'anime': keyword}, timeout=10)
        data = res.json()
        st.session_state.current_animes = data.get('animes', [])[:CONFIG['SEARCH_MAX']]
        update_realtime_log(f"搜索成功: 找到 {len(st.session_state.current_animes)} 条资源。", log_area)
        st.rerun()
    except Exception as e:
        update_realtime_log(f"搜索失败: {str(e)}", log_area)

if st.session_state.is_running and current_eps:
    indices = []
    try:
        clean_range = range_input.strip()
        if clean_range == "0": indices = list(range(len(current_eps)))
        elif "-" in clean_range:
            s_n, e_n = map(int, clean_range.split("-"))
            indices = [i for i in range(s_n-1, e_n) if 0 <= i < len(current_eps)]
        else: indices = [int(clean_range)-1] if 0 < int(clean_range) <= len(current_eps) else []
    except: st.session_state.is_running = False; st.rerun()

    if indices:
        p_bar = st.progress(0)
        total_count = len(indices)
        current_fmt = CONFIG['NAME_FORMAT']
        current_keyword = st.session_state.search_keyword if st.session_state.search_keyword else keyword

        # --- 新增：文件名重复检测预判 ---
        if total_count > 1:
            test_names = []
            for idx in indices:
                raw_title = current_eps[idx]['episodeTitle']
                clean_raw_title = re.sub(r'^[【\[].+?[\]】]\s*', '', raw_title)
                ep_tag = f"E{idx+1:02d}"
                name = current_fmt.replace("[标题]", current_keyword).replace("[集数]", ep_tag).replace("[原]", clean_raw_title)
                test_names.append(name)
            
            # 如果去重后数量变少了，说明有重复
            if len(set(test_names)) < total_count:
                update_realtime_log("⚠️ 检测到命名格式会导致文件名重复，已自动追加[集数]以作区分。", log_area)
                if "[集数]" not in current_fmt:
                    current_fmt += "[集数]"
        # ----------------------------

        for i, idx in enumerate(indices):
            if not st.session_state.is_running: break 
            ep_data = current_eps[idx]
            
            raw_title = ep_data['episodeTitle']
            clean_raw_title = re.sub(r'^[【\[].+?[\]】]\s*', '', raw_title)
            
            # 电影且单集时不加 E01
            if is_movie_resource and total_count == 1:
                ep_tag = ""
            else:
                ep_tag = f"E{idx+1:02d}"
            
            save_name = current_fmt.replace("[标题]", current_keyword).replace("[集数]", ep_tag).replace("[原]", clean_raw_title)
            save_name = re.sub(r'\s+', ' ', save_name).strip()
            save_name = re.sub(r'[\\/:*?"<>|]', '_', save_name)
            
            suffix = ".ass" if CONFIG['SAVE_AS_ASS'] else ".xml"
            
            update_realtime_log(f"正在下载: {save_name}{suffix}", log_area)
            try:
                r = requests.get(f"{CONFIG['BASE_URL']}/api/v2/comment/{ep_data['episodeId']}", params={'format': 'xml'}, timeout=12)
                content = convert_xml_to_ass(r.text) if CONFIG['SAVE_AS_ASS'] else r.text
                if content:
                    st.session_state.download_files[f"{save_name}{suffix}"] = content
            except: pass
            p_bar.progress((i + 1) / len(indices))
        
        st.session_state.is_running = False
        update_realtime_log("任务操作结束。", log_area)
        st.rerun()
