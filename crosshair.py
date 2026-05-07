#!/usr/bin/env python3
"""
3D 멀미 방지 조준선 오버레이
"""

import tkinter as tk
from tkinter import ttk, colorchooser, messagebox
import ctypes
from ctypes import windll
import sys
import threading
import json
import os
import traceback

# ── 에러 로그 ─────────────────────────────────────────────────────────────────
if getattr(sys, 'frozen', False):
    _BASE_DIR = os.path.dirname(sys.executable)
else:
    _BASE_DIR = os.path.dirname(os.path.abspath(__file__))

LOG_PATH = os.path.join(_BASE_DIR, '3dmermy_error.log')

def log_error(msg: str):
    try:
        with open(LOG_PATH, 'a', encoding='utf-8') as f:
            f.write(msg + '\n')
    except Exception:
        pass

# ── PIL/pystray ───────────────────────────────────────────────────────────────
try:
    from PIL import Image, ImageDraw
    import pystray
    HAS_TRAY = True
except Exception as e:
    HAS_TRAY = False
    log_error(f"[pystray/PIL import fail] {e}")

# ── Windows API ───────────────────────────────────────────────────────────────
GWL_EXSTYLE       = -20
WS_EX_LAYERED     = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_NOACTIVATE  = 0x08000000
WS_EX_TOPMOST     = 0x00000008
LWA_ALPHA         = 0x00000002
HWND_TOPMOST      = -1
SWP_NOMOVE        = 0x0002
SWP_NOSIZE        = 0x0001
SWP_NOACTIVATE    = 0x0010
RGN_OR            = 2

# ── 설정 ─────────────────────────────────────────────────────────────────────
SETTINGS_PATH = os.path.join(os.path.expanduser('~'), '.3dmermy_crosshair.json')

DEFAULTS = {
    'color':        '#00FF41',
    'center_size':  30,
    'center_gap':   6,
    'center_dot':   False,
    'dot_size':     3,
    'edge_size':    25,
    'edge_gap':     4,
    'thickness':    2,
    'show_center':  True,
    'show_edges':   True,
    'visible':      True,
    'edge_margin':  35,
    'opacity':      100,        # 0~100 (%)
}

def load_settings() -> dict:
    s = DEFAULTS.copy()
    try:
        if os.path.exists(SETTINGS_PATH):
            with open(SETTINGS_PATH, 'r', encoding='utf-8') as f:
                s.update(json.load(f))
    except Exception:
        pass
    return s

def save_settings(s: dict):
    try:
        with open(SETTINGS_PATH, 'w', encoding='utf-8') as f:
            json.dump(s, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


# ── 메인 앱 ───────────────────────────────────────────────────────────────────
class CrosshairApp:

    def __init__(self):
        self.s = load_settings()
        self._tray = None
        self._overlay_hwnd = 0

        self.root = tk.Tk()
        self.root.withdraw()

        self.sw = self.root.winfo_screenwidth()
        self.sh = self.root.winfo_screenheight()

        self._build_overlay()
        self._build_settings_window()

        if HAS_TRAY:
            self._start_tray()

        self.settings_win.deiconify()
        self.settings_win.lift()

        self._running = True
        threading.Thread(target=self._topmost_thread, daemon=True).start()
        self._keep_topmost()

    # ── 오버레이 ─────────────────────────────────────────────────────────────
    def _build_overlay(self):
        BG = '#010101'

        ov = tk.Toplevel(self.root)
        ov.geometry(f"{self.sw}x{self.sh}+0+0")
        ov.overrideredirect(True)
        # tkinter 자체 topmost — HWND가 어디에 있든 확실하게 최상위
        ov.wm_attributes('-topmost', True)
        ov.configure(bg=BG)

        self.canvas = tk.Canvas(
            ov, width=self.sw, height=self.sh,
            bg=BG, highlightthickness=0
        )
        self.canvas.pack()
        self.overlay = ov
        ov.update()

        # Win32 HWND 획득 — wm_frame() 우선, 실패 시 winfo_id() 폴백
        try:
            hwnd = int(ov.wm_frame(), 16)
            if not hwnd:
                raise ValueError
        except Exception:
            hwnd = ov.winfo_id()

        self._overlay_hwnd = hwnd

        # 오버레이는 표시만 하고 마우스 클릭은 뒤의 게임/앱으로 통과시킨다.
        # SetWindowRgn은 그릴 영역을 조준선 픽셀로 제한하고,
        # WS_EX_TRANSPARENT는 그 픽셀 위에서도 클릭을 먹지 않게 한다.
        style = windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        style |= WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_NOACTIVATE | WS_EX_TOPMOST
        windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)
        windll.user32.SetWindowPos(
            hwnd, HWND_TOPMOST, 0, 0, 0, 0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE
        )

        self._apply_opacity()

        self._draw()

    def _apply_opacity(self):
        """전체 불투명도 적용 (LWA_ALPHA만 사용 — 색상 키 불필요)"""
        if not self._overlay_hwnd:
            return
        alpha = max(1, min(255, int(self.s.get('opacity', 100) / 100 * 255)))
        try:
            windll.user32.SetLayeredWindowAttributes(
                self._overlay_hwnd, 0, alpha, LWA_ALPHA
            )
        except Exception as e:
            log_error(f"[SetLayeredWindowAttributes] {e}")

    def _update_region(self):
        """조준선 픽셀 영역만 창 region으로 남겨 배경 전체가 가려지지 않게 한다.
        실제 클릭 통과는 WS_EX_TRANSPARENT 확장 스타일에서 처리한다.
        """
        if not self._overlay_hwnd:
            return
        s = self.s
        t = max(1, int(s['thickness']))
        pad = t // 2 + 2
        cx, cy = self.sw // 2, self.sh // 2

        rgn = windll.gdi32.CreateRectRgn(0, 0, 0, 0)

        def add(x1, y1, x2, y2):
            r = windll.gdi32.CreateRectRgn(
                max(0, min(x1, x2) - pad),
                max(0, min(y1, y2) - pad),
                min(self.sw, max(x1, x2) + pad),
                min(self.sh, max(y1, y2) + pad),
            )
            windll.gdi32.CombineRgn(rgn, rgn, r, RGN_OR)
            windll.gdi32.DeleteObject(r)

        if s.get('visible', True):
            if s['show_center']:
                sz  = int(s['center_size'])
                gap = int(s['center_gap'])
                add(cx - sz, cy, cx - gap, cy)
                add(cx + gap, cy, cx + sz,  cy)
                add(cx, cy - sz, cx, cy - gap)
                add(cx, cy + gap, cx, cy + sz)
                if s['center_dot']:
                    ds = int(s['dot_size'])
                    add(cx - ds, cy - ds, cx + ds, cy + ds)
            if s['show_edges']:
                esz = int(s['edge_size'])
                m   = max(int(s['edge_margin']), esz + 5)
                add(cx, m - esz,              cx, m + esz)
                add(cx, self.sh - m - esz,    cx, self.sh - m + esz)
                add(m - esz,          cy,     m + esz,         cy)
                add(self.sw - m - esz, cy,    self.sw - m + esz, cy)

        windll.user32.SetWindowRgn(self._overlay_hwnd, rgn, True)

    def _draw(self):
        self.canvas.delete('all')

        # 불투명도 적용
        self._apply_opacity()

        if not self.s.get('visible', True):
            self._update_region()
            return

        s  = self.s
        c  = s['color']
        t  = max(1, int(s['thickness']))
        cx = self.sw // 2
        cy = self.sh // 2

        # 중앙 조준선
        if s['show_center']:
            sz  = int(s['center_size'])
            gap = int(s['center_gap'])
            self._cross(cx, cy, sz, gap, c, t)
            if s['center_dot']:
                ds = int(s['dot_size'])
                self.canvas.create_oval(
                    cx - ds, cy - ds, cx + ds, cy + ds,
                    fill=c, outline=''
                )

        # 가장자리 마커 — 상/하: 세로선(|), 좌/우: 가로선(—)
        if s['show_edges']:
            esz = int(s['edge_size'])
            m   = max(int(s['edge_margin']), esz + 5)
            kw  = dict(fill=c, width=t)
            # 위: 세로선
            self.canvas.create_line(cx, m - esz, cx, m + esz, **kw)
            # 아래: 세로선
            self.canvas.create_line(cx, self.sh - m - esz, cx, self.sh - m + esz, **kw)
            # 왼쪽: 가로선
            self.canvas.create_line(m - esz, cy, m + esz, cy, **kw)
            # 오른쪽: 가로선
            self.canvas.create_line(self.sw - m - esz, cy, self.sw - m + esz, cy, **kw)

        self._update_region()

    def _cross(self, x, y, size, gap, color, width):
        kw = dict(fill=color, width=width)
        self.canvas.create_line(x - size, y,        x - gap,  y,        **kw)
        self.canvas.create_line(x + gap,  y,        x + size, y,        **kw)
        self.canvas.create_line(x,        y - size,  x,        y - gap,  **kw)
        self.canvas.create_line(x,        y + gap,   x,        y + size, **kw)

    def _topmost_thread(self):
        """별도 스레드에서 1ms 간격으로 SetWindowPos 재확인 (게임 60fps 대응)"""
        import time
        while self._running:
            if self._overlay_hwnd:
                try:
                    windll.user32.SetWindowPos(
                        self._overlay_hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                        SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE
                    )
                except Exception:
                    pass
            time.sleep(0.001)

    def _keep_topmost(self):
        """500ms마다 tkinter topmost 재확인 (스레드가 Win32는 처리)"""
        try:
            self.overlay.wm_attributes('-topmost', True)
        except Exception:
            pass
        self.root.after(500, self._keep_topmost)

    # ── 설정창 ───────────────────────────────────────────────────────────────
    def _build_settings_window(self):
        win = tk.Toplevel(self.root)
        win.title("조준선 설정 — 3D 멀미 방지")
        win.geometry("380x640+60+60")
        win.resizable(False, False)
        win.protocol("WM_DELETE_WINDOW", win.withdraw)
        self.settings_win = win
        win.withdraw()
        self._build_settings_ui(win)

    def _build_settings_ui(self, win):
        s = self.s

        hdr = tk.Frame(win, bg='#1a1a2e', pady=8)
        hdr.pack(fill='x')
        tk.Label(hdr, text="3D 멀미 방지 조준선 설정",
                 bg='#1a1a2e', fg='#00FF41',
                 font=('Malgun Gothic', 13, 'bold')).pack()
        tk.Label(hdr, text="설정 변경 시 조준선에 즉시 반영됩니다",
                 bg='#1a1a2e', fg='#888888',
                 font=('Malgun Gothic', 8)).pack()

        main = ttk.Frame(win)
        main.pack(fill='both', expand=True, padx=15, pady=6)

        # 색상
        cf = ttk.LabelFrame(main, text="색상")
        cf.pack(fill='x', pady=4)
        row = ttk.Frame(cf)
        row.pack(pady=5)
        self._color_preview = tk.Label(row, bg=s['color'], width=5, height=1, relief='groove')
        self._color_preview.pack(side='left', padx=(6, 4))
        self._color_label = tk.Label(row, text=s['color'], font=('Courier', 9))
        self._color_label.pack(side='left', padx=2)
        ttk.Button(row, text="색상 선택...", command=self._pick_color).pack(side='left', padx=6)

        # 중앙 조준선
        cent = ttk.LabelFrame(main, text="중앙 조준선")
        cent.pack(fill='x', pady=4)
        self._v_show_center = tk.BooleanVar(value=s['show_center'])
        ttk.Checkbutton(cent, text="표시", variable=self._v_show_center,
                        command=self._refresh_checks).pack(anchor='w', padx=6)
        self._slider(cent, "크기",    5,  80, s['center_size'], 'center_size')
        self._slider(cent, "간격",    0,  30, s['center_gap'],  'center_gap')
        self._v_center_dot = tk.BooleanVar(value=s['center_dot'])
        ttk.Checkbutton(cent, text="중앙 점 표시", variable=self._v_center_dot,
                        command=self._refresh_checks).pack(anchor='w', padx=6)
        self._slider(cent, "점 크기", 1,  15, s['dot_size'], 'dot_size')

        # 가장자리 마커
        edge = ttk.LabelFrame(main, text="가장자리 마커  (상 / 하 / 좌 / 우)")
        edge.pack(fill='x', pady=4)
        self._v_show_edges = tk.BooleanVar(value=s['show_edges'])
        ttk.Checkbutton(edge, text="표시", variable=self._v_show_edges,
                        command=self._refresh_checks).pack(anchor='w', padx=6)
        self._slider(edge, "크기",     5,  80, s['edge_size'],   'edge_size')
        self._slider(edge, "화면 여백", 5,  80, s['edge_margin'], 'edge_margin')

        # 공통
        com = ttk.LabelFrame(main, text="공통")
        com.pack(fill='x', pady=4)
        self._slider(com, "선 두께",  1, 50,  s['thickness'], 'thickness')
        self._slider(com, "투명도(%)", 10, 100, s['opacity'],   'opacity')

        # 버튼
        btns = ttk.Frame(main)
        btns.pack(fill='x', pady=8)
        ttk.Button(btns, text="저장 후 닫기",       command=self._save_and_close).pack(side='left',  padx=4)
        ttk.Button(btns, text="조준선 보이기/숨기기", command=self._toggle_visible).pack(side='left',  padx=4)
        ttk.Button(btns, text="종료",              command=self._quit).pack(side='right', padx=4)

        hint = ("트레이 아이콘(우클릭) → 설정 열기 / 조준선 토글"
                if HAS_TRAY else
                "이 창을 닫아도 조준선은 유지됩니다")
        tk.Label(win, text=hint, font=('Malgun Gothic', 8), fg='gray').pack(pady=(0, 6))

    def _slider(self, parent, label, from_, to_, init, key):
        row = ttk.Frame(parent)
        row.pack(fill='x', padx=8, pady=2)
        ttk.Label(row, text=label, width=9).pack(side='left')
        var = tk.IntVar(value=int(init))

        def on_change(val, _key=key, _var=var):
            self.s[_key] = int(float(val))
            self._draw()

        ttk.Scale(row, from_=from_, to=to_, variable=var,
                  command=on_change, orient='horizontal').pack(side='left', fill='x', expand=True)
        ttk.Label(row, textvariable=var, width=4).pack(side='left')

    def _pick_color(self):
        result = colorchooser.askcolor(
            color=self.s['color'], title="조준선 색상 선택",
            parent=self.settings_win
        )
        if result and result[1]:
            self.s['color'] = result[1]
            self._color_preview.configure(bg=result[1])
            self._color_label.configure(text=result[1])
            self._draw()

    def _refresh_checks(self):
        self.s['show_center'] = self._v_show_center.get()
        self.s['show_edges']  = self._v_show_edges.get()
        self.s['center_dot']  = self._v_center_dot.get()
        self._draw()

    def _toggle_visible(self):
        self.s['visible'] = not self.s.get('visible', True)
        self._draw()

    def _save_and_close(self):
        save_settings(self.s)
        self.settings_win.withdraw()

    def _quit(self):
        self._running = False
        save_settings(self.s)
        if self._tray:
            self._tray.stop()
        self.root.quit()

    # ── 시스템 트레이 ─────────────────────────────────────────────────────────
    def _start_tray(self):
        try:
            img = Image.new('RGBA', (64, 64), (0, 0, 0, 0))
            d = ImageDraw.Draw(img)
            green = (0, 255, 65, 255)
            d.line([(32, 6),  (32, 26)], fill=green, width=4)
            d.line([(32, 38), (32, 58)], fill=green, width=4)
            d.line([(6,  32), (26, 32)], fill=green, width=4)
            d.line([(38, 32), (58, 32)], fill=green, width=4)
            d.ellipse([(26, 26), (38, 38)], outline=green, width=2)

            menu = pystray.Menu(
                pystray.MenuItem("설정 열기",        self._tray_open_settings, default=True),
                pystray.MenuItem("조준선 보이기/숨기기", self._tray_toggle),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("종료",             self._tray_quit),
            )
            icon = pystray.Icon("3dmermy", img, "3D 멀미 방지 조준선", menu)
            self._tray = icon
            threading.Thread(target=icon.run, daemon=True).start()
        except Exception as e:
            log_error(f"[tray error] {e}")

    def _tray_open_settings(self, *_):
        self.root.after(0, self._open_settings)

    def _open_settings(self):
        self.settings_win.deiconify()
        self.settings_win.lift()
        self.settings_win.focus_force()

    def _tray_toggle(self, *_):
        self.root.after(0, self._toggle_visible)

    def _tray_quit(self, *_):
        self.root.after(0, self._quit)

    def run(self):
        self.root.mainloop()


# ── 진입점 ────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    try:
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            try:
                ctypes.windll.user32.SetProcessDPIAware()
            except Exception:
                pass

        app = CrosshairApp()
        app.run()

    except Exception:
        err = traceback.format_exc()
        log_error(err)
        try:
            messagebox.showerror(
                "3D Crosshair Error",
                f"Startup error. Check log:\n{LOG_PATH}\n\n{err[:300]}"
            )
        except Exception:
            pass
