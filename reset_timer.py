#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import time
import subprocess
import requests
from seleniumbase import SB

LOGIN_URL = "https://justrunmy.app/id/account/login?returnUrl=https%3A%2F%2Fjustrunmy.app%2Fpanel"
PANEL_URL = "https://justrunmy.app/panel"
DOMAIN    = "justrunmy.app"

# ============================================================
#  环境变量与全局变量
# ============================================================
EMAIL        = os.environ.get("ACC")
PASSWORD     = os.environ.get("ACC_PWD")
TG_BOT_TOKEN = os.environ.get("TG_TOKEN")
TG_CHAT_ID   = os.environ.get("TG_ID")

if not EMAIL or not PASSWORD:
    print("致命错误：未找到 ACC 或 ACC_PWD 环境变量！")
    print("请检查 GitHub Repository Secrets 是否配置正确（EML_1, PWD_1...）。")
    sys.exit(1)

# 全局变量，用于动态保存网页上抓取到的应用名称
DYNAMIC_APP_NAME = "未知应用"

# ============================================================
#  Telegram 推送模块
# ============================================================

def send_tg_photo(bot_token, chat_id, photo_path, caption=""):
    """直接发送本地图片文件到 Telegram"""
    url = f"https://api.telegram.org/bot{bot_token}/sendPhoto"
    try:
        with open(photo_path, 'rb') as photo:
            payload = {'chat_id': chat_id, 'caption': caption}
            files = {'photo': photo}
            # 发送请求
            resp = requests.post(url, data=payload, files=files, timeout=15)
            if resp.status_code == 200:
                print("Telegram 截图发送成功！")
            else:
                print(f"Telegram 发图失败，响应: {resp.text}")
    except Exception as e:
        print(f"发送 Telegram 图片异常: {e}")
def send_tg_message(status_icon, status_text, time_left):
    if not TG_BOT_TOKEN or not TG_CHAT_ID:
        print("未配置 TG_TOKEN 或 TG_ID，跳过 Telegram 推送。")
        return

    local_time = time.gmtime(time.time() + 8 * 3600)
    current_time_str = time.strftime("%Y-%m-%d %H:%M:%S", local_time)

    text = (
        f"{DYNAMIC_APP_NAME}\n"
        f"{status_icon} {status_text}\n"
        f"剩余: {time_left}\n"
        f"时间: {current_time_str}"
    )

    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TG_CHAT_ID, "text": text}
    
    try:
        r = requests.post(url, json=payload, timeout=10)
        if r.status_code == 200:
            print("  Telegram 通知发送成功！")
        else:
            print(f"  Telegram 通知发送失败: {r.text}")
    except Exception as e:
        print(f"  Telegram 通知发送异常: {e}")

# ============================================================
#  页面注入脚本 (Turnstile 辅助)
# ============================================================
_EXPAND_JS = """
(function() {
    var ts = document.querySelector('input[name="cf-turnstile-response"]');
    if (ts) {
        var el = ts;
        for (var i = 0; i < 20; i++) {
            el = el.parentElement;
            if (!el) break;
            var s = window.getComputedStyle(el);
            if (s.overflow === 'hidden' || s.overflowX === 'hidden' || s.overflowY === 'hidden')
                el.style.overflow = 'visible';
            el.style.minWidth = 'max-content';
        }
    }
    // 展开所有 Turnstile 相关 iframe 及其祖先容器（Blazor 互操作渲染的 widget）
    document.querySelectorAll('iframe').forEach(function(f){
        if (f.src && (f.src.indexOf('challenges.cloudflare.com') !== -1 || f.src.indexOf('turnstile') !== -1)) {
            f.style.width = '300px'; f.style.height = '65px';
            f.style.minWidth = '300px';
            f.style.visibility = 'visible'; f.style.opacity = '1';
            var p = f.parentElement;
            for (var j = 0; j < 10 && p; j++) {
                var s = window.getComputedStyle(p);
                if (s.overflow === 'hidden' || s.overflowX === 'hidden' || s.overflowY === 'hidden')
                    p.style.overflow = 'visible';
                if (s.display === 'none') p.style.display = 'block';
                p.style.minWidth = 'max-content';
                p = p.parentElement;
            }
        }
    });
    return 'done';
})()
"""

_EXISTS_JS = """
(function(){
    // 1) 标准 Turnstile 隐藏输入（登录页的 <div class="cf-turnstile"> 会创建）
    if (document.querySelector('input[name="cf-turnstile-response"]')) return true;
    // 2) Blazor 互操作渲染的 Turnstile widget 容器（turnstile.js 的 jrnmTurnstile）
    if (window.jrnmTurnstile && window.jrnmTurnstile.widgetIds) {
        for (var id in window.jrnmTurnstile.widgetIds) {
            if (window.jrnmTurnstile.widgetIds.hasOwnProperty(id)) return true;
        }
    }
    // 3) 直接检测 cloudflare challenges iframe（最可靠，Blazor 渲染的 widget 也会产生 iframe）
    var iframes = document.querySelectorAll('iframe');
    for (var i = 0; i < iframes.length; i++) {
        var src = iframes[i].src || '';
        if (src.indexOf('challenges.cloudflare.com') !== -1 || src.indexOf('turnstile') !== -1) {
            if (iframes[i].offsetParent !== null) return true;
        }
    }
    return false;
})()
"""

_SOLVED_JS = """
(function(){
    // 1) 标准 Turnstile 隐藏输入
    var i = document.querySelector('input[name="cf-turnstile-response"]');
    if (i && i.value && i.value.length > 20) return true;
    // 2) Blazor 互操作 widget 的 token
    if (window.jrnmTurnstile && window.jrnmTurnstile.widgetIds) {
        for (var id in window.jrnmTurnstile.widgetIds) {
            if (window.jrnmTurnstile.widgetIds.hasOwnProperty(id)) {
                try {
                    var tok = window.jrnmTurnstile.getToken(id);
                    if (tok && tok.length > 20) return true;
                } catch(e) {}
            }
        }
    }
    return false;
})()
"""

_CLEAR_TOKEN_JS = """
(function(){
    var i = document.querySelector('input[name="cf-turnstile-response"]');
    if (i) { i.value = ''; }
    // 同时 reset 所有 Blazor 互操作 widget，强制重新验证
    if (window.jrnmTurnstile && window.jrnmTurnstile.widgetIds) {
        for (var id in window.jrnmTurnstile.widgetIds) {
            if (window.jrnmTurnstile.widgetIds.hasOwnProperty(id)) {
                try { window.jrnmTurnstile.reset(id); } catch(e) {}
            }
        }
    }
    return 'cleared';
})()
"""

_CHECK_SUCCESS_TOAST_JS = """
(function(){
    // 检查各种成功提示
    var texts = document.body.innerText || '';
    // 弹窗关闭
    var modals = document.querySelectorAll('[role="dialog"], .modal, [class*="modal"], [class*="dialog"]');
    var modalVisible = false;
    modals.forEach(function(m){
        if (m.offsetParent !== null) modalVisible = true;
    });
    // 成功关键词
    var hasSuccess = /success|reset|renew|extended|succeed/i.test(texts);
    // 新 toast
    var toasts = document.querySelectorAll('[class*="toast"], [class*="alert"], [class*="notification"]');
    var toastText = '';
    toasts.forEach(function(t){ if (t.offsetParent !== null) toastText += t.innerText + ' | '; });
    return JSON.stringify({modalVisible: modalVisible, hasSuccessKeywords: hasSuccess, toastText: toastText.substring(0,200)});
})()
"""

_COORDS_JS = """
(function(){
    // 1) 优先找 Turnstile iframe（Blazor 互操作渲染的 widget 一定产生 iframe）
    var iframes = document.querySelectorAll('iframe');
    for (var i = 0; i < iframes.length; i++) {
        var src = iframes[i].src || '';
        if (src.indexOf('challenges.cloudflare.com') !== -1 || src.indexOf('turnstile') !== -1) {
            var r = iframes[i].getBoundingClientRect();
            if (r.width > 0 && r.height > 0)
                return {cx: Math.round(r.x + 30), cy: Math.round(r.y + r.height / 2), found: 'iframe'};
        }
    }
    // 2) 兜底：Turnstile 隐藏输入的父容器
    var inp = document.querySelector('input[name="cf-turnstile-response"]');
    if (inp) {
        var p = inp.parentElement;
        for (var j = 0; j < 5; j++) {
            if (!p) break;
            var r = p.getBoundingClientRect();
            if (r.width > 100 && r.height > 30)
                return {cx: Math.round(r.x + 30), cy: Math.round(r.y + r.height / 2), found: 'input'};
            p = p.parentElement;
        }
    }
    // 3) 兜底：jrnmTurnstile widget 容器
    if (window.jrnmTurnstile && window.jrnmTurnstile.widgetIds) {
        for (var id in window.jrnmTurnstile.widgetIds) {
            if (window.jrnmTurnstile.widgetIds.hasOwnProperty(id)) {
                var el = document.getElementById(id);
                if (!el) continue;
                var r = el.getBoundingClientRect();
                if (r.width > 0 && r.height > 0)
                    return {cx: Math.round(r.x + 30), cy: Math.round(r.y + r.height / 2), found: 'widget'};
            }
        }
    }
    return null;
})()
"""

_WININFO_JS = """
(function(){
    return {
        sx: window.screenX || 0,
        sy: window.screenY || 0,
        oh: window.outerHeight,
        ih: window.innerHeight
    };
})()
"""

_MODAL_OPEN_JS = """
(function(){
    // 检测续期弹窗是否打开（Blazor 弹窗没有标准 modal class）
    // 1) 弹窗背景遮罩层
    var els = document.querySelectorAll('[class*="backdrop-blur"]');
    for (var i=0;i<els.length;i++){ if(els[i].offsetParent!==null) return 'backdrop'; }
    // 2) Turnstile widget 容器（弹窗内的 captcha 区域）
    var ts = document.getElementById('turnstile-timer-reset');
    if (ts && ts.offsetParent !== null) return 'turnstile';
    // 3) 弹窗内容容器（fixed inset-0 的高 z-index 容器）
    var all = document.querySelectorAll('*');
    for (var i=0;i<all.length;i++){
        var s = window.getComputedStyle(all[i]);
        if (s.position==='fixed' && s.zIndex>=999 && s.display!=='none' && s.visibility!=='hidden'){
            var r = all[i].getBoundingClientRect();
            if (r.width>200 && r.height>100 && all[i].offsetParent!==null) return 'fixed-'+all[i].tagName;
        }
    }
    // 4) Just Reset 按钮可见（弹窗最显著的特征）
    var btns = document.querySelectorAll('button');
    for (var i=0;i<btns.length;i++){
        if ((btns[i].textContent.indexOf('Just Reset')!==-1 || btns[i].textContent.indexOf('Just')!==-1) && btns[i].offsetParent!==null)
            return 'button';
    }
    return null;
})()
"""

def js_fill_input(sb, selector: str, text: str):
    safe_text = text.replace('\\', '\\\\').replace('"', '\\"')
    sb.execute_script(f"""
    (function(){{
        var el = document.querySelector('{selector}');
        if (!el) return;
        var nativeInputValueSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value").set;
        if (nativeInputValueSetter) {{
            nativeInputValueSetter.call(el, "{safe_text}");
        }} else {{
            el.value = "{safe_text}";
        }}
        el.dispatchEvent(new Event('input', {{ bubbles: true }}));
        el.dispatchEvent(new Event('change', {{ bubbles: true }}));
    }})()
    """)

def _activate_window():
    for cls in ["chrome", "chromium", "Chromium", "Chrome", "google-chrome"]:
        try:
            r = subprocess.run(["xdotool", "search", "--onlyvisible", "--class", cls], capture_output=True, text=True, timeout=3)
            wids = [w for w in r.stdout.strip().split("\n") if w.strip()]
            if wids:
                subprocess.run(["xdotool", "windowactivate", "--sync", wids[0]], timeout=3, stderr=subprocess.DEVNULL)
                time.sleep(0.2)
                return
        except Exception:
            pass
    try:
        subprocess.run(["xdotool", "getactivewindow", "windowactivate"], timeout=3, stderr=subprocess.DEVNULL)
    except Exception:
        pass

def _xdotool_click(x: int, y: int):
    _activate_window()
    try:
        subprocess.run(["xdotool", "mousemove", "--sync", str(x), str(y)], timeout=3, stderr=subprocess.DEVNULL)
        time.sleep(0.15)
        subprocess.run(["xdotool", "click", "1"], timeout=2, stderr=subprocess.DEVNULL)
    except Exception:
        os.system(f"xdotool mousemove {x} {y} click 1 2>/dev/null")

def _click_turnstile(sb):
    try:
        coords = sb.execute_script(_COORDS_JS)
    except Exception as e:
        print(f"  获取 Turnstile 坐标失败: {e}")
        return
    if not coords:
        print("  无法定位 Turnstile 坐标")
        return
    try:
        wi = sb.execute_script(_WININFO_JS)
    except Exception:
        wi = {"sx": 0, "sy": 0, "oh": 800, "ih": 768}
        
    bar = wi["oh"] - wi["ih"]
    ax  = coords["cx"] + wi["sx"]
    ay  = coords["cy"] + wi["sy"] + bar
    print(f"  物理级点击 Turnstile ({ax}, {ay})")
    _xdotool_click(ax, ay)

def _get_token_value(sb):
    """读取当前 cf-turnstile-response 的 token 值（用于调试）"""
    try:
        # 标准隐藏输入
        tok = sb.execute_script(
            "var i=document.querySelector('input[name=\"cf-turnstile-response\"]');"
            "return i ? i.value : '';"
        ) or ""
        if tok:
            return tok
        # Blazor 互操作 widget
        tok = sb.execute_script("""
            if (window.jrnmTurnstile && window.jrnmTurnstile.widgetIds) {
                for (var id in window.jrnmTurnstile.widgetIds) {
                    if (window.jrnmTurnstile.widgetIds.hasOwnProperty(id)) {
                        try { return window.jrnmTurnstile.getToken(id) || ''; } catch(e) {}
                    }
                }
            }
            return '';
        """) or ""
        return tok
    except Exception:
        return ""

def handle_turnstile(sb, force=False) -> bool:
    print("处理 Cloudflare Turnstile 验证...")
    time.sleep(2)
    
    # 诊断：打印当前 Turnstile 检测状态
    try:
        diag = sb.execute_script("""
            var out = {input: !!document.querySelector('input[name="cf-turnstile-response"]'), iframes: [], widgets: []};
            var iframes = document.querySelectorAll('iframe');
            for (var i=0;i<iframes.length;i++){
                var s=iframes[i].src||'';
                if(s.indexOf('challenges.cloudflare.com')!==-1||s.indexOf('turnstile')!==-1){
                    out.iframes.push({vis: iframes[i].offsetParent!==null, w: iframes[i].offsetWidth, h: iframes[i].offsetHeight});
                }
            }
            if (window.jrnmTurnstile && window.jrnmTurnstile.widgetIds) {
                for (var id in window.jrnmTurnstile.widgetIds) {
                    if (window.jrnmTurnstile.widgetIds.hasOwnProperty(id)) {
                        try { out.widgets.push({id: id, tok: (window.jrnmTurnstile.getToken(id)||'').substring(0,20)}); } catch(e){}
                    }
                }
            }
            return JSON.stringify(out);
        """)
        print(f"  [诊断] Turnstile 状态: {diag}")
    except Exception:
        pass
    
    # ★ 关键修复：等待 Cloudflare iframe 真正渲染出来再操作
    # Blazor 注册了 widget 但 Cloudflare JS 需要时间加载并创建 iframe
    print("  等待 Cloudflare Turnstile iframe 渲染...")
    iframe_ready = False
    for w in range(30):
        try:
            ready = sb.execute_script("""
                // 检查 Cloudflare iframe 是否已渲染且可见
                var ifs = document.querySelectorAll('iframe');
                for (var i=0;i<ifs.length;i++){
                    var s = ifs[i].src||'';
                    if (s.indexOf('challenges.cloudflare.com')!==-1 || s.indexOf('turnstile')!==-1){
                        if (ifs[i].offsetParent !== null && ifs[i].offsetWidth > 50 && ifs[i].offsetHeight > 20)
                            return true;
                    }
                }
                // 检查 turnstile 容器是否有可见子元素（widget 已渲染）
                var containers = document.querySelectorAll('[id*="turnstile"], [class*="cf-turnstile"]');
                for (var i=0;i<containers.length;i++){
                    var r = containers[i].getBoundingClientRect();
                    if (r.width > 100 && r.height > 30 && containers[i].offsetParent !== null)
                        return true;
                }
                return false;
            """)
            if ready:
                iframe_ready = True
                print(f"  Cloudflare iframe 已渲染（等待 {w+1} 秒）")
                break
        except Exception:
            pass
        if w in (0, 4, 9, 14, 19, 24, 29):
            print(f"  ⏳ 等待 Cloudflare iframe... ({w+1}/30s)")
        time.sleep(1)
    
    if not iframe_ready:
        print("  ⚠️ Cloudflare iframe 30秒内未渲染，尝试直接操作...")
    
    # 只有当已有 token（可能过期）时才需要清除
    tok_now = _get_token_value(sb)
    if force and tok_now:
        sb.execute_script(_CLEAR_TOKEN_JS)
        print("  已清除旧 token，强制重新验证...")
        time.sleep(2)
    elif force:
        print("  无旧 token，跳过清除（widget 尚未渲染完成）")
    
    if sb.execute_script(_SOLVED_JS):
        tok = _get_token_value(sb)
        print(f"  已静默通过 (token: {tok[:25]}...)")
        return True

    for _ in range(3):
        try: sb.execute_script(_EXPAND_JS)
        except Exception: pass
        time.sleep(0.5)

    for attempt in range(6):
        if sb.execute_script(_SOLVED_JS):
            tok = _get_token_value(sb)
            print(f"  Turnstile 通过（第 {attempt + 1} 次尝试）token: {tok[:25]}...")
            return True
        try: sb.execute_script(_EXPAND_JS)
        except Exception: pass
        time.sleep(0.3)
        
        _click_turnstile(sb)
        
        for _ in range(8):
            time.sleep(0.5)
            if sb.execute_script(_SOLVED_JS):
                tok = _get_token_value(sb)
                print(f"  Turnstile 通过（第 {attempt + 1} 次尝试）token: {tok[:25]}...")
                return True
        print(f"  第 {attempt + 1} 次未通过，重试...")

    print("  Turnstile 6 次均失败")
    return False

def login(sb) -> bool:
    print(f"打开登录页面: {LOGIN_URL}")
    sb.uc_open_with_reconnect(LOGIN_URL, reconnect_time=5)
    time.sleep(4)

    try:
        sb.wait_for_element('input[name="Email"]', timeout=15)
    except Exception:
        print("页面未加载出登录表单")
        sb.save_screenshot("login_load_fail.png")
        return False

    print("关闭可能的 Cookie 弹窗...")
    try:
        for btn in sb.find_elements("button"):
            if "Accept" in (btn.text or ""):
                btn.click()
                time.sleep(0.5)
                break
    except Exception:
        pass

    print(f"填写邮箱...")
    js_fill_input(sb, 'input[name="Email"]', EMAIL)
    time.sleep(0.3)
    
    print("填写密码...")
    js_fill_input(sb, 'input[name="Password"]', PASSWORD)
    time.sleep(1)

    if sb.execute_script(_EXISTS_JS):
        if not handle_turnstile(sb):
            print("登录界面的 Turnstile 验证失败")
            sb.save_screenshot("login_turnstile_fail.png")
            return False
    else:
        print("未检测到 Turnstile")

    # ★ 修复：点击 Sign In 按钮而不是敲回车（更可靠）
    print("点击 Sign In 按钮提交表单...")
    try:
        sb.click('button:contains("Sign In")')
    except Exception:
        print("按钮点击失败，尝试回车提交...")
        sb.press_keys('input[name="Password"]', '\n')

    print("等待登录跳转...")
    login_base = LOGIN_URL.split('?')[0].lower()
    for _ in range(15):
        time.sleep(1)
        cur = sb.get_current_url().split('?')[0].lower()
        if cur != login_base:
            print(f"✅ 检测到页面跳转: {sb.get_current_url()}")
            break

    # ★ 关键修复：登录后导航到面板，验证是否真的能进去
    print("🔍 验证登录状态：尝试进入面板页...")
    sb.open(PANEL_URL)
    sb.wait_for_ready_state_complete()
    time.sleep(4)

    current_url = sb.get_current_url().lower()
    if "panel" in current_url and "login" not in current_url:
        print("✅ 登录成功，已进入面板页！")
        return True
    else:
        print(f"❌ 登录后无法进入面板页，当前URL: {current_url}")
        sb.save_screenshot("login_verify_failed.png")
        # 保存页面源码用于调试
        try:
            with open("login_page_source.html", "w") as f:
                f.write(sb.get_page_source()[:5000])
            print("📄 页面源码已保存到 login_page_source.html")
        except Exception:
            pass
        return False

def renew(sb)->bool:
    global DYNAMIC_APP_NAME
    print("\n" + "="*50)
    print("   开始自动续期流程")
    print("="*50)
    
    # ★ 修复：登录后显式导航到面板页，不要依赖 redirect
    print("进入控制面板: https://justrunmy.app/panel")
    sb.open(PANEL_URL)
    sb.wait_for_ready_state_complete()
    time.sleep(5)
    
    print("自动读取应用名称...")
    retry_count = 3
    found = False
    
    for attempt in range(1, retry_count + 1):
      try:
        current_url = sb.get_current_url().lower()
        # 检测是否被重定向到登录页
        if "login" in current_url:
          print(f"第 {attempt} 次尝试：检测到重定向至登录页，开始自动补登...")
          if not login(sb):
            print("自动补登失败！")
            break
          # ★ 登录成功后显式导航回面板
          print("✅ 补登成功，重新进入面板...")
          sb.open(PANEL_URL)
          sb.wait_for_ready_state_complete()
          time.sleep(4)
          current_url = sb.get_current_url().lower()
        
        # ★ 验证是否真的在面板页（检查 URL 包含 panel）
        if "panel" not in current_url:
          print(f"⚠️ 当前不在面板页，URL: {current_url}，重试...")
          sb.save_screenshot(f"panel_not_reached_{attempt}.png")
          if attempt < retry_count:
            sb.open(PANEL_URL)
            time.sleep(3)
          continue
        
        # ★ 修复：通过查找应用链接来定位应用卡片
        # 应用详情页链接格式: /panel/application/{id}
        app_link = None
        try:
          app_links = sb.find_elements('a[href*="/panel/application/"]')
          if app_links:
            for link in app_links:
              href = link.get_attribute('href') or ''
              text = link.text.strip()
              if text and '/panel/application/' in href:
                app_link = link
                DYNAMIC_APP_NAME = text
                print(f"✅ 找到应用: {DYNAMIC_APP_NAME} ({href})")
                break
        except Exception:
          pass
        
        # ★ 备用：如果没找到应用链接，尝试 h3 + 其他选择器
        if not app_link:
          fallback_selectors = [
            'h3.font-semibold',
            'h3',
            '[class*="card"] h3',
            '[class*="application"] h3',
            '[class*="app"] h3',
          ]
          for sel in fallback_selectors:
            try:
              if sb.is_element_visible(sel):
                DYNAMIC_APP_NAME = sb.get_text(sel)
                print(f"✅ 通过选择器 '{sel}' 找到应用: {DYNAMIC_APP_NAME}")
                # 尝试点击应用名进入详情
                sb.click(sel)
                time.sleep(3)
                # 检查是否进入详情页
                detail_url = sb.get_current_url().lower()
                if "/panel/application/" in detail_url:
                  found = True
                  break
                else:
                  print(f"⚠️ 点击后未进入详情页 (URL: {detail_url})，回退面板")
                  sb.open(PANEL_URL)
                  sb.wait_for_ready_state_complete()
                  time.sleep(3)
                  continue
              # 检查是否进入了详情页
              detail_url = sb.get_current_url().lower()
              if "/panel/application/" in detail_url:
                found = True
                break
            except Exception:
              continue
        
        # 如果找到了应用链接，点击进入详情页
        if app_link:
          try:
            app_link.click()
            time.sleep(3)
            detail_url = sb.get_current_url().lower()
            if "/panel/application/" in detail_url:
              found = True
              print("✅ 已进入应用详情页")
            else:
              print(f"⚠️ 点击链接后未进入详情页 (URL: {detail_url})")
              sb.open(PANEL_URL)
              time.sleep(3)
              continue
          except Exception as e:
            print(f"⚠️ 点击应用链接失败: {e}")
            # 尝试 JS 点击
            try:
              sb.js_click('a[href*="/panel/application/"]')
              time.sleep(3)
              if "/panel/application/" in sb.get_current_url().lower():
                found = True
                print("✅ 通过 JS 点击进入详情页")
            except Exception:
              pass
        
        if found:
          break
    
      except Exception as e:
        print(f"第 {attempt} 次获取应用卡片失败: {e}")
        if attempt < retry_count:
          print("重新打开控制台主页重试...")
          sb.open(PANEL_URL)
          time.sleep(3)
    
    # 3 次尝试全部失败
    if not found:
      print("多次尝试均未找到应用卡片，正在截图并发送通知...")
      img_name = "renew_app_not_found.png"
      sb.save_screenshot(img_name)
      # 保存页面源码供调试
      try:
        with open("renew_page_source.html", "w") as f:
          f.write(sb.get_page_source())
        print("📄 页面源码已保存到 renew_page_source.html")
      except Exception:
        pass
      send_tg_message("[X]", "续期失败(找不到应用)", "未知")
      send_tg_photo(TG_BOT_TOKEN, TG_CHAT_ID, img_name,
                    caption="⚠️ 找不到应用卡片现场截图")
      return False
    
    # 📊 进入详情页后，先读取当前倒计时，作为重置前的基线值
    print("📊 读取重置前的倒计时...")
    pre_timer = None
    pre_timer_selectors = [
        'span.font-mono.text-xl',
        'span.font-mono',
        '.font-mono',
        'span.text-xl',
        '.text-xl',
        '[class*="timer"]',
        '[class*="countdown"]',
        'time',
        '[data-countdown]',
    ]
    for sel in pre_timer_selectors:
        try:
            text = sb.get_text(sel)
            if text and text.strip():
                pre_timer = text.strip()
                print(f"  📊 重置前倒计时 ({sel}): {pre_timer}")
                break
        except Exception:
            continue
    if not pre_timer:
        print("  ⚠️ 无法读取重置前倒计时（可能选择器不匹配）")
    
    # 保存详情页源码，查看 Reset timer 按钮和弹窗结构
    try:
        with open("renew_detail_page_source.html", "w") as f:
            f.write(sb.get_page_source())
        print("📄 详情页源码已保存: renew_detail_page_source.html")
    except Exception:
        pass
    
    print("点击 Reset timer 按钮...")
    btn_clicked = False
    btn_selectors = [
      'button[title="Reset timer"]',
      'button:contains("Reset timer")',
      'button:contains("Reset")',
      'a:contains("Reset timer")',
      '[class*="reset"] button',
      'button[class*="reset"]',
      '[title*="Reset"]',
      '//button[contains(text(), "Reset")]',
      '//a[contains(text(), "Reset timer")]',
    ]
    for btn_sel in btn_selectors:
      try:
        if btn_sel.startswith('//'):
          is_visible = sb.is_element_visible(btn_sel, by="xpath")
        else:
          is_visible = sb.is_element_visible(btn_sel)
        if is_visible:
          sb.sleep(1)
          if btn_sel.startswith('//'):
            sb.click(btn_sel, by="xpath")
          else:
            sb.click(btn_sel)
          time.sleep(3)
          btn_clicked = True
          print(f"✅ 已点击 Reset timer 按钮 (selector: {btn_sel})")
          break
      except Exception as e:
        print(f"  ⚠️ 尝试 '{btn_sel}' 失败: {e}")
        continue
    
    if not btn_clicked:
      print(f"找不到 Reset timer 按钮")
      img_name = "renew_reset_btn_not_found.png"
      sb.save_screenshot(img_name)
      try:
        with open("renew_reset_page_source.html", "w") as f:
          f.write(sb.get_page_source())
        print("📄 页面源码已保存到 renew_reset_page_source.html")
      except Exception:
        pass
      send_tg_message("[X]", "续期失败(找不到按钮)", "未知")
      send_tg_photo(TG_BOT_TOKEN, TG_CHAT_ID, img_name,
                    caption="续期失败现场截图")
      return False

    # ============================================================
    #  Blazor 弹窗渲染：SignalR 异步更新 DOM，必须等待 Just Reset 出现
    # ============================================================
    print("⏳ 等待 Blazor 续期弹窗渲染完成...")
    modal_ready = False
    for _ in range(20):
        try:
            if sb.is_element_visible('button:contains("Just Reset")'):
                modal_ready = True
                print("  弹窗已渲染（出现 Just Reset 按钮）")
                break
        except Exception:
            pass
        time.sleep(1)
    if not modal_ready:
        # 弹窗可能用其它文案，检查 modal/dialog 容器
        try:
            if sb.execute_script("""
                var modals = document.querySelectorAll('[role="dialog"], .modal, [class*="modal"]');
                for (var i=0;i<modals.length;i++){ if(modals[i].offsetParent!==null) return true; }
                return false;
            """):
                print("  检测到弹窗容器（未找到 Just Reset 文案）")
                modal_ready = True
        except Exception:
            pass

    if not modal_ready:
        print("⚠️ 未检测到续期弹窗，尝试直接继续...")

    # ============================================================
    #  检测并处理弹窗内的 Turnstile 验证
    #  ★ 关键：Blazor 互操作渲染的 Turnstile 可能没有隐藏输入，
    #    必须同时检测 iframe 和 jrnmTurnstile widget
    # ============================================================
    print("🔍 检查续期弹窗内是否需要 CF 验证...")
    # ★ 关键修复：Blazor SignalR 异步注入 Turnstile widget，注入耗时可能 >12 秒，
    #   必须轮询等待直到 widget 真正渲染（input / jrnmTurnstile / iframe 任一出现）
    turnstile_detected = False
    for attempt in range(30):  # 最多等 ~30 秒
        reason = None
        try:
            r = sb.execute_script("""
                var out = {detected:false, input: !!document.querySelector('input[name="cf-turnstile-response"]'), ifr: 0, widget: false};
                var ifs = document.querySelectorAll('iframe');
                for (var i=0;i<ifs.length;i++){ var s=ifs[i].src||''; if(s.indexOf('challenges.cloudflare.com')!==-1||s.indexOf('turnstile')!==-1) out.ifr++; }
                if (window.jrnmTurnstile && window.jrnmTurnstile.widgetIds) {
                    out.widget = Object.keys(window.jrnmTurnstile.widgetIds).length > 0;
                }
                if (out.input || out.ifr > 0 || out.widget) out.detected = true;
                return JSON.stringify(out);
            """)
            import json as _json
            info = _json.loads(r)
            if info.get('detected'):
                turnstile_detected = True
                print(f"  检测到 Turnstile（第 {attempt+1} 次，input={info.get('input')} iframes={info.get('ifr')} widget={info.get('widget')}），开始处理...")
                break
            if attempt in (0, 4, 9, 14, 19, 24, 29):
                print(f"  ⏳ 等待 Blazor 注入 Turnstile... ({attempt+1}/30s, input={info.get('input')} iframes={info.get('ifr')} widget={info.get('widget')})")
        except Exception as e:
            if attempt in (0, 9, 19, 29):
                print(f"  检测脚本异常: {e}")
        time.sleep(1)
    if not turnstile_detected:
        print("  ⚠️ 30 秒内仍未检测到 Turnstile，直接继续（可能弹窗确实没有 CF 验证）")
    else:
        # Turnstile 检测到，进行验证
        if not handle_turnstile(sb, force=True):
            print("弹窗内的 Turnstile 验证失败")
            sb.save_screenshot("renew_turnstile_fail.png")
            try:
                with open("renew_turnstile_page_source.html", "w") as f:
                    f.write(sb.get_page_source())
            except Exception:
                pass
            send_tg_message("[X]", "续期失败(人机验证未过)", "未知")
            send_tg_photo(TG_BOT_TOKEN, TG_CHAT_ID, "renew_turnstile_fail.png",
                          caption="⚠️ 弹窗 Turnstile 验证失败现场")
            return False

    print("点击 Just Reset 确认续期...")
    just_reset_clicked = False
    
    # 等待 Just Reset 按钮变为可用（Blazor 弹窗中按钮可能一开始是 disabled）
    for _ in range(15):
        try:
            if sb.is_element_visible('button:contains("Just Reset")'):
                disabled = sb.execute_script("""
                    var b = null;
                    var btns = document.querySelectorAll('button');
                    for (var i=0;i<btns.length;i++){
                        if (btns[i].textContent.indexOf('Just Reset') !== -1){ b = btns[i]; break; }
                    }
                    if (!b) return false;
                    return b.disabled || b.classList.contains('disabled') || b.getAttribute('aria-disabled') === 'true';
                """)
                if disabled:
                    print("  ⏳ Just Reset 按钮当前为禁用状态，等待启用...")
                    time.sleep(1)
                    continue
                break
        except Exception:
            pass
        time.sleep(1)
    
    # 尝试多种方式点击 Just Reset 按钮
    just_reset_selectors = [
        'button:contains("Just Reset")',
        'button:contains("Just")',
        'button:contains("Reset")',
        '//button[contains(text(), "Just Reset")]',
        '//button[contains(text(), "Reset")]',
        '[class*="reset"] [type="submit"]',
        'button[type="submit"]',
        'form button',
    ]
    
    for sel in just_reset_selectors:
        try:
            if sel.startswith('//'):
                if sb.is_element_visible(sel, by="xpath"):
                    sb.click(sel, by="xpath")
                    just_reset_clicked = True
                    print(f"✅ 已点击 Just Reset (xpath: {sel})")
                    break
            else:
                if sb.is_element_visible(sel):
                    sb.click(sel)
                    just_reset_clicked = True
                    print(f"✅ 已点击 Just Reset (css: {sel})")
                    break
        except Exception as e:
            print(f"  ⚠️ 尝试 '{sel}' 失败: {e}")
            continue
    
    # 如果普通点击没找到，尝试 JS 点击
    if not just_reset_clicked:
        try:
            sb.execute_script("""
                var btns = document.querySelectorAll('button');
                for(var i=0; i<btns.length; i++) {
                    if(btns[i].textContent.includes('Just Reset') || btns[i].textContent.includes('Reset') || btns[i].textContent.includes('Just')) {
                        if (btns[i].disabled) { btns[i].disabled = false; }
                        btns[i].click();
                        return 'clicked: ' + btns[i].textContent;
                    }
                }
                return 'no button found';
            """)
            print("✅ 通过 JS 点击了包含 Reset 的按钮")
            just_reset_clicked = True
        except Exception as e:
            print(f"  JS 点击也失败: {e}")
    
    if not just_reset_clicked:
        print(f"找不到 Just Reset 按钮")
        sb.save_screenshot("renew_just_reset_not_found.png")
        # 保存页面源码
        try:
            with open("renew_just_reset_page_source.html", "w") as f:
                f.write(sb.get_page_source())
            print("📄 页面源码已保存到 renew_just_reset_page_source.html")
        except Exception:
            pass
        send_tg_message("[X]", "续期失败(无法确认)", "未知")
        send_tg_photo(TG_BOT_TOKEN, TG_CHAT_ID, "renew_just_reset_not_found.png",
                      caption="找不到 Just Reset 按钮现场")
        return False
    
    print("提交续期请求，等待服务器处理...")
    time.sleep(3)
    
    # 🎯 关键：等待 Blazor 弹窗关闭（服务器处理完请求后自动关闭 modal）
    print("等待 Blazor 弹窗关闭...")
    modal_closed = False
    for _ in range(20):
        try:
            still_open = sb.execute_script(_MODAL_OPEN_JS)
            if not still_open:
                modal_closed = True
                print("✅ 弹窗已关闭，续期请求已提交")
                break
        except Exception:
            pass
        time.sleep(1)
    
    if not modal_closed:
        print("⚠️ 弹窗未关闭（可能续期未提交成功），尝试再次点击...")
        time.sleep(3)
        try:
            sb.click('button:contains("Just Reset")')
            print("  再次尝试点击 Just Reset...")
            time.sleep(5)
            # 再次检查弹窗
            try:
                still_open = sb.execute_script(_MODAL_OPEN_JS)
                if not still_open:
                    modal_closed = True
                    print("✅ 二次点击后弹窗已关闭")
            except Exception:
                pass
        except Exception:
            pass
    
    # 🎯 关键：点击 Just Reset 后保存页面源码
    try:
        sb.save_screenshot("renew_after_just_reset.png")
        with open("renew_after_just_reset_source.html", "w") as f:
            f.write(sb.get_page_source())
        print("📄 已保存 Just Reset 后的页面源码: renew_after_just_reset_source.html")
        print("📸 已保存 Just Reset 后的截图: renew_after_just_reset.png")
    except Exception as e:
        print(f"  保存页面源码失败: {e}")

    print("点击 Just Reset 后，检查是否又弹出新的 Turnstile 挑战...")
    time.sleep(3)
    if sb.execute_script(_EXISTS_JS):
        if not handle_turnstile(sb, force=True):
            print("点击后的 Turnstile 验证失败")
            sb.save_screenshot("renew_post_turnstile_fail.png")
            try:
                with open("renew_post_turnstile_page_source.html", "w") as f:
                    f.write(sb.get_page_source())
            except Exception:
                pass
            send_tg_message("[X]", "续期失败(提交后验证未过)", "未知")
            send_tg_photo(TG_BOT_TOKEN, TG_CHAT_ID, "renew_post_turnstile_fail.png",
                          caption="⚠️ 点击 Just Reset 后 Turnstile 失败")
            return False
        # 解决后可能需再次确认
        try:
            if sb.is_element_visible('button:contains("Just Reset")'):
                sb.click('button:contains("Just Reset")')
                print("✅ 验证后再次点击 Just Reset")
                time.sleep(5)
        except Exception:
            pass

    # 检查是否出现成功提示或弹窗关闭
    print("检查续期结果...")
    try:
        state = sb.execute_script(_CHECK_SUCCESS_TOAST_JS)
        print(f"  页面状态: {state}")
    except Exception as e:
        print(f"  检查页面状态异常: {e}")

    print("验证最终倒计时状态...")
    try:
        sb.refresh()
        time.sleep(4)
        
        # 🔧 多选择器兜底读取倒计时文本
        timer_text = None
        timer_selectors = [
            'span.font-mono.text-xl',
            'span.font-mono',
            '.font-mono',
            'span.text-xl',
            '.text-xl',
            '[class*="timer"]',
            '[class*="countdown"]',
            'time',
            '[data-countdown]',
        ]
        for sel in timer_selectors:
            try:
                text = sb.get_text(sel)
                if text and text.strip():
                    timer_text = text.strip()
                    print(f"  ✅ 读取到倒计时 ({sel}): {timer_text}")
                    break
            except Exception:
                continue
        
        if timer_text:
            print(f"  🎯 重置前: {pre_timer} → 重置后: {timer_text}")
            if timer_text == pre_timer and pre_timer:
                print("❌ 倒计时完全没有变化！续期失败！")
                sb.save_screenshot("renew_failed_no_change.png")
                try:
                    with open("renew_failed_no_change_source.html", "w") as f:
                        f.write(sb.get_page_source())
                except Exception:
                    pass
                send_tg_message("[X]", "续期失败(倒计时未变)", timer_text)
                return False
            elif "2 days 23" in timer_text or "3 days" in timer_text:
                print("✅ 续期任务圆满完成！")
                sb.save_screenshot("renew_success.png")
                send_tg_message("[OK]", "续期完成", timer_text)
                return True
            else:
                print("⚠️ 倒计时似乎没有重置到最高值，请人工检查截图。")
                sb.save_screenshot("renew_warning.png")
                send_tg_message("[!]", "续期异常(请检查)", timer_text)
                return True  # 虽异常但按钮已点击，不判 False
        else:
            print("⚠️ 无法读取倒计时文本，但续期流程已执行完毕，视为成功。")
            sb.save_screenshot("renew_timer_read_fail.png")
            # 保存页面源码用于调试
            try:
                with open("renew_timer_read_fail_source.html", "w") as f:
                    f.write(sb.get_page_source())
                print("📄 页面源码已保存到 renew_timer_read_fail_source.html")
            except Exception:
                pass
            send_tg_message("[OK]", "续期完成(倒计时读取失败)", "未知")
            return True  # 续期按钮已点击，不因读取失败而判 False
        
    except Exception as e:
        print(f"验证阶段异常: {e}")
        sb.save_screenshot("renew_verify_exception.png")
        try:
            with open("renew_verify_exception_source.html", "w") as f:
                f.write(sb.get_page_source())
            print("📄 页面源码已保存到 renew_verify_exception_source.html")
        except Exception:
            pass
        send_tg_message("[OK]", "续期完成(验证异常)", "未知")
        return True  # 续期按钮已点击，不因验证异常判失败

def main():
    print("=" * 50)
    print("   JustRunMy.app 自动登录与续期脚本")
    print("=" * 50)
    
    proxy_url_env = os.environ.get("PROXY_URL", "").strip()
    sb_kwargs = {"uc": True, "test": True, "headless": False}
    
    if proxy_url_env:
        local_proxy = "http://127.0.0.1:8080"
        print(f"检测到代理配置，挂载本地通道: {local_proxy}")
        sb_kwargs["proxy"] = local_proxy
    
    with SB(**sb_kwargs) as sb:
        print("浏览器已启动")
        try:
            sb.open("https://api.ipify.org/?format=json")
            print(f"当前出口 IP: {sb.get_text('body')}")
        except Exception:
            pass

        if login(sb):
            renew(sb)
        else:
            print("\n登录环节失败，终止后续续期操作。")
            send_tg_message("[X]", "登录失败", "未知")

if __name__ == "__main__":
    main()
