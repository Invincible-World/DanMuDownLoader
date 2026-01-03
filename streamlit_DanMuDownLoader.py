import requests
import re
import os
import io
import json
import zipfile
import time
import xml.etree.ElementTree as ET
from datetime import datetime
import streamlit as st

# ================= 1. 配置管理与初始化 =================
DEFAULT_CONFIG = {
    "SEARCH_MAX": 15,            # 搜索结果显示的最大数量，防止搜索列表过长
    "SAVE_AS_ASS": True,         # 是否保存为 ASS 格式（True 为 ASS，False 为原始 XML）
    "ASS_FONT": "Microsoft YaHei", # 弹幕字体名称，需确保电脑已安装该字体
    "NAME_FORMAT": "[标题][集数]", # 输出文件名的格式模板：支持 [标题]、[集数]、[序号]、[原]
    "ASS_FONT_BOLD": True,       # 弹幕字体是否加粗
    "ASS_FONT_SIZE": 50,         # 弹幕基础字号大小
    "ASS_DURATION": 25,          # 滚动弹幕从右侧到左侧的总耗时（秒），数值越大滚动越慢
    "ASS_DISPLAY_AREA": 0.2,     # 弹幕显示区域占比（0.1~1.0），0.2 表示弹幕只占用屏幕上方 20% 的高度
    "STOP_DURATION": 5,          # 顶底固定弹幕的停留时间（秒）。设为 0 时，自动转为普通滚动弹幕
    "ASS_OPACITY": 0.8,          # 弹幕不透明度（0.0~1.0），0.0 为完全透明，1.0 为完全不透明
    "ASS_OUTLINE": 1,            # 弹幕字体边缘描边的宽度（像素）
    "BASE_URL": "https://dan-mu-api.netlify.app/87654321", # 弹幕搜索与下载的 API 接口根地址
}
CACHE_FILE = "config_cache.json"

def load_local_config():
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                return {**DEFAULT_CONFIG, **json.load(f)}
        except:
            return DEFAULT_CONFIG
    return DEFAULT_CONFIG

def save_local_config(config_dict):
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(config_dict, f, ensure_ascii=False, indent=4)

# 初始化 Session State
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
    try:
        alpha = int(255 * (1 - max(0.0, min(1.0, opacity_pct))))
        return f"{alpha:02x}"
    except:
        return "00"

def dec_to_ass_color(dec_color):
    try:
        hex_color = f"{int(dec_color):06x}"
        r, g, b = hex_color[0:2], hex_color[2:4], hex_color[4:6]
        return f"&H{get_ass_opacity_hex(CONFIG['ASS_OPACITY'])}{b}{g}{r}"
    except:
        return f"&H{get_ass_opacity_hex(CONFIG['ASS_OPACITY'])}FFFFFF"

def convert_xml_to_ass(xml_content):
    PLAY_RES_X, PLAY_RES_Y = 1920, 1080
    header = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {PLAY_RES_X}",
        f"PlayResY: {PLAY_RES_Y}",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Default,{CONFIG['ASS_FONT']},{CONFIG['ASS_FONT_SIZE']},&H{get_ass_opacity_hex(CONFIG['ASS_OPACITY'])}FFFFFF,&H00FFFFFF,&H00000000,&H00000000,{1 if CONFIG['ASS_FONT_BOLD'] else 0},0,0,0,100,100,0,0,1,{CONFIG['ASS_OUTLINE']},0,7,10,10,10,1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"
    ]
    try:
        xml_content = re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F]', '', xml_content)
        root = ET.fromstring(xml_content.encode('utf-8'))
        display_h = int(PLAY_RES_Y * CONFIG['ASS_DISPLAY_AREA'])
        rows_scroll, rows_top = [None] * (display_h + 1), [None] * (display_h + 1)
        
        def format_time(t):
            t = max(0, t)
            return f"{int(t//3600)}:{int((t%3600)//60):02d}:{t%60:05.2f}"
            
        danmus = []
        for d in root.findall('d'):
            p = d.get('p').split(',')
            if len(p) >= 4:
                text = d.text if d.text else ""
                w = sum(2.0 if ord(c) > 127 else 1.0 for c in text) * (CONFIG['ASS_FONT_SIZE'] / 2)
                mode = int(p[1])
                if CONFIG['STOP_DURATION'] <= 0 and mode in (4, 5):
                    mode = 1
                danmus.append({
                    'start': float(p[0]), 
                    'mode': mode, 
                    'color': dec_to_ass_color(p[3]), 
                    'text': text, 'w': w, 
                    'h': int(CONFIG['ASS_FONT_SIZE'] * 1.2)
                })
        
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
                        target_row = r
                        break
                if target_row != -1:
                    for i in range(target_row, min(target_row + h, display_h)):
                        rows_scroll[i] = (start_t, w)
                    y = target_row + CONFIG['ASS_FONT_SIZE']
                    move = f"\\move({PLAY_RES_X + 50},{y},{-w - 50},{y})"
                    events.append(f"Dialogue: 0,{format_time(start_t)},{format_time(start_t+CONFIG['ASS_DURATION'])},Default,,0,0,0,,{{{move}\\c{c['color']}}}{c['text']}")
            elif m in (4, 5):
                for r in range(0, display_h - h, 8):
                    if not rows_top[r] or rows_top[r] < start_t:
                        target_row = r
                        break
                if target_row != -1:
                    for i in range(target_row, min(target_row + h, display_h)):
                        rows_top[i] = start_t + CONFIG['STOP_DURATION']
                    y = target_row + CONFIG['ASS_FONT_SIZE']
                    align = "\\an8" if m == 5 else "\\an2"
                    pos_y = y if m == 5 else PLAY_RES_Y - target_row - 10
                    events.append(f"Dialogue: 1,{format_time(start_t)},{format_time(start_t+CONFIG['STOP_DURATION'])},Default,,0,0,0,,{{{align}\\pos({PLAY_RES_X/2},{pos_y})\\c{c['color']}}}{c['text']}")
        return "\n".join(header + events)
    except:
        return None

# ================= 3. UI 布局与状态 =================
if "logs" not in st.session_state:
    st.session_state.logs = []
if "is_running" not in st.session_state:
    st.session_state.is_running = False
if "final_zip" not in st.session_state:
    st.session_state.final_zip = None
if "single_file" not in st.session_state:
    st.session_state.single_file = None
if "download_files" not in st.session_state:
    st.session_state.download_files = {}

def update_realtime_log(msg, placeholder=None):
    current_time = datetime.now().strftime("%H:%M:%S")
    st.session_state.logs.append(f"[{current_time}] {msg}")
    if placeholder:
        log_html = f'<div class="log-container" id="log-box">{"<br>".join(st.session_state.logs)}</div>'
        placeholder.markdown(log_html, unsafe_allow_html=True)

st.set_page_config(page_title="弹幕助手 Pro", page_icon="🎬", layout="centered")

# CSS 样式恢复
st.markdown("""
    <style>
    .log-container { 
        height: 180px; 
        overflow-y: auto; 
        background-color: #1e1e1e; 
        color: #00ff00; 
        border: 2px solid #444; 
        border-radius: 8px; 
        padding: 10px; 
        font-family: monospace; 
        font-size: 12px; 
        line-height: 1.4; 
        margin-bottom: 10px; 
    }
    div[data-testid="stFormSubmitButton"] button {
        height: 45px; 
        font-size: 18px !important; 
        background-color: #ff4b4b !important; 
        border-radius: 8px !important;
    }
    .stButton button { 
        width: 100%; 
    }
    </style>
""", unsafe_allow_html=True)

# 侧边栏
with st.sidebar:
    st.header("⚙️ 全局配置")
    c_btn1, c_btn2 = st.columns(2)
    with c_btn1:
        if st.button("💾 保存设置"):
            save_local_config(CONFIG)
            st.success("已保存")
    with c_btn2:
        st.button("🔄 重置设置", on_click=reset_config_callback)
    
    st.write("---")
    with st.expander("🎨 命名与样式", expanded=True):
        st.checkbox("保存为 ASS 格式", key="cfg_SAVE_AS_ASS")
        st.write("格式占位符：")
        tag_col1, tag_col2, tag_col3, tag_col4, tag_col5 = st.columns([1, 1, 1, 1, 1.2])
        with tag_col1: st.button("[标题]", on_click=add_format_tag, args=("[标题]",), use_container_width=True)
        with tag_col2: st.button("[集数]", on_click=add_format_tag, args=("[集数]",), use_container_width=True)
        with tag_col3: st.button("[序号]", on_click=add_format_tag, args=("[序号]",), use_container_width=True)
        with tag_col4: st.button("[原]", on_click=add_format_tag, args=("[原]",), use_container_width=True)
        with tag_col5: st.button("🗑️ 清空", on_click=clear_format, use_container_width=True)
        
        st.text_input("文件命名格式", key="cfg_NAME_FORMAT")
        st.text_input("字体名称", key="cfg_ASS_FONT")
        st.slider("字体大小", 10, 100, key="cfg_ASS_FONT_SIZE")
        st.slider("不透明度", 0.0, 1.0, key="cfg_ASS_OPACITY")
        st.checkbox("加粗字体", key="cfg_ASS_FONT_BOLD")
        st.number_input("描边宽度", 0, 5, key="cfg_ASS_OUTLINE")

    with st.expander("⏱️ 时间与显示", expanded=True):
        st.number_input("滚动时长(秒)", 5, 60, key="cfg_ASS_DURATION")
        st.number_input("停留时长(秒)", 0, 20, key="cfg_STOP_DURATION")
        st.slider("显示区域占比", 0.1, 1.0, key="cfg_ASS_DISPLAY_AREA")

    with st.expander("🌐 网络与搜索", expanded=False):
        st.text_input("API 根地址", key="cfg_BASE_URL")
        st.number_input("搜索显示上限", 1, 50, key="cfg_SEARCH_MAX")

st.title("🎬 弹幕助手 Web Pro")

# 搜索框
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
        if p not in platform_map: 
            platform_map[p] = []
        platform_map[p].append(ep)
        
    p_choice = st.selectbox("选择来源平台", list(platform_map.keys()))
    current_eps = platform_map[p_choice]
    
    with st.expander(f"📖 剧集预览 (共 {len(current_eps)} 集)", expanded=False):
        st.markdown("  \n".join([f"**[{i+1}]** {ep['episodeTitle']}" for i, ep in enumerate(current_eps)]))

# 底部按钮逻辑
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

# 打包逻辑
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
    st.session_state.logs = []
    st.session_state.final_zip = None
    st.session_state.single_file = None
    st.session_state.download_files = {}
    st.session_state.is_running = False
    st.rerun()

# 日志显示区
log_area = st.empty()
log_area.markdown(f'<div class="log-container" id="log-box">{"<br>".join(st.session_state.logs) if st.session_state.logs else "等待任务启动..."}</div>', unsafe_allow_html=True)
st.components.v1.html("""<script>function sc(){var b=window.parent.document.getElementById('log-box');if(b)b.scrollTop=b.scrollHeight;}setInterval(sc,500);</script>""", height=0)

# ================= 4. 后台下载转换逻辑 =================
def apply_name_format(fmt, kw, idx, is_movie, total, raw_t):
    res_name = fmt.replace("[标题]", kw).replace("[原]", raw_t)
    ep_tag = "" if is_movie and total == 1 else f"E{idx+1:02d}"
    res_name = res_name.replace("[集数]", ep_tag)
    idx_tag_default = "" if is_movie and total == 1 else f"{idx+1:02d}"
    res_name = res_name.replace("[序号]", idx_tag_default)
    matches = re.findall(r'\[序号(\d+)\]', res_name)
    for m in matches:
        width = int(m)
        dynamic_tag = "" if is_movie and total == 1 else f"{idx+1:0{width}d}"
        res_name = res_name.replace(f"[序号{m}]", dynamic_tag)
    return res_name

# 搜索执行
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

# 下载执行
if st.session_state.is_running and current_eps:
    indices = []
    try:
        clean_range = range_input.strip()
        if clean_range == "0":
            indices = list(range(len(current_eps)))
        elif "-" in clean_range:
            s_n, e_n = map(int, clean_range.split("-"))
            indices = [i for i in range(s_n-1, e_n) if 0 <= i < len(current_eps)]
        else:
            indices = [int(clean_range)-1] if 0 < int(clean_range) <= len(current_eps) else []
    except:
        st.session_state.is_running = False
        st.rerun()

    if indices:
        p_bar = st.progress(0)
        total_count = len(indices)
        current_fmt = CONFIG['NAME_FORMAT']
        current_keyword = st.session_state.search_keyword if st.session_state.search_keyword else keyword

        # 检查重名风险
        if total_count > 1:
            test_names = []
            for idx in indices:
                raw_title = current_eps[idx]['episodeTitle']
                clean_raw_title = re.sub(r'^[【\[].+?[\]】]\s*', '', raw_title)
                test_names.append(apply_name_format(current_fmt, current_keyword, idx, is_movie_resource, total_count, clean_raw_title))
            if len(set(test_names)) < total_count:
                update_realtime_log("⚠️ 检测到命名格式会导致文件名重复，已自动追加[集数]以作区分。", log_area)
                if "[集数]" not in current_fmt:
                    current_fmt += "[集数]"

        # 循环下载
        for i, idx in enumerate(indices):
            if not st.session_state.is_running:
                break 
                
            ep_data = current_eps[idx]
            raw_title = ep_data['episodeTitle']
            clean_raw_title = re.sub(r'^[【\[].+?[\]】]\s*', '', raw_title)
            save_name = apply_name_format(current_fmt, current_keyword, idx, is_movie_resource, total_count, clean_raw_title)
            save_name = re.sub(r'[\\/:*?"<>|]', '_', re.sub(r'\s+', ' ', save_name).strip())
            suffix = ".ass" if CONFIG['SAVE_AS_ASS'] else ".xml"
            
            update_realtime_log(f"正在下载[{i+1}/{total_count}]: {save_name}{suffix}", log_area)
            
            success = False
            # 重试循环 (0-5 共 6 次机会)
            for retry in range(6): 
                if retry > 0:
                    time.sleep(2)
                try:
                    r = requests.get(f"{CONFIG['BASE_URL']}/api/v2/comment/{ep_data['episodeId']}", params={'format': 'xml'}, timeout=12)
                    r.raise_for_status()
                    
                    content = convert_xml_to_ass(r.text) if CONFIG['SAVE_AS_ASS'] else r.text
                    
                    if content:
                        st.session_state.download_files[f"{save_name}{suffix}"] = content
                        size_kb = len(content.encode('utf-8')) / 1024
                        update_realtime_log(f"✅ 下载完成[{i+1}/{total_count}]: {save_name}{suffix} ({size_kb:.1f}kb)", log_area)
                        success = True
                        break
                except Exception as e:
                    err = f"{type(e).__name__}: {str(e)}"
                    if retry < 5:
                        update_realtime_log(f"⚠️ 下载出错({err})，正在重试 {retry+1}/5...", log_area)
                    else:
                        update_realtime_log(f"❌ 5次重试均失败: {err}", log_area)
                        update_realtime_log("🛑 触发熔断保护，任务已终止。", log_area)
                        st.session_state.is_running = False
                        break
            
            if not success:
                break
            p_bar.progress((i + 1) / len(indices))
            
        st.session_state.is_running = False
        update_realtime_log("任务结束。", log_area)
        st.rerun()
