#!/usr/bin/env python3
"""
Patch ThingsBoard ui-ngx jar with:
1. Virtuoso NetSoft branding assets (logos, favicons)
2. Dark Charcoal Theme (#2B2F3A / #1F232C) for navbar, sidebar, buttons
3. Auto-redirect on /login directly to Keycloak SSO
4. Title and 'Powered by Virtuoso NetSoft v.4.3.1.6' text
"""
import os
import shutil
import gzip
import zipfile
import io

EXTRACT_DIR = '/tmp/tb_extract'
PUBLIC_DIR = '/tmp/tb_extract/ui/public'
BRANDING_DIR = '/home/ubuntu/thingsboard/docker/branding/virtuoso-netsoft'

DARK_CHARCOAL_CSS = """
    /* Virtuoso NetSoft Dark Charcoal Theme (#2B2F3A / #1F232C) */
    .mat-toolbar.mat-primary,
    .tb-primary-toolbar,
    .mat-mdc-toolbar.mat-primary,
    mat-toolbar[color="primary"] {
      background-color: #2B2F3A !important;
      color: #ffffff !important;
    }

    mat-sidenav.tb-site-sidenav,
    .tb-site-sidenav,
    .tb-side-menu-toolbar,
    .tb-nav-header {
      background-color: #1F232C !important;
    }

    .tb-nav-header-toolbar,
    .tb-nav-logo {
      background-color: #2B2F3A !important;
      border-bottom: 1px solid rgba(255, 255, 255, 0.08) !important;
      width: 100% !important;
      justify-content: flex-start !important;
      padding-left: 8px !important;
      box-sizing: border-box !important;
    }

    .tb-site-sidenav .mat-mdc-list-item,
    .tb-site-sidenav .mat-nav-list .mat-list-item,
    .tb-site-sidenav .tb-side-menu-toolbar .mat-mdc-list-item {
      color: #CBD5E1 !important;
    }

    .tb-site-sidenav .mat-mdc-list-item:hover,
    .tb-site-sidenav .mat-nav-list .mat-list-item:hover {
      background-color: rgba(255, 255, 255, 0.06) !important;
    }

    .tb-site-sidenav .mat-mdc-list-item.tb-active,
    .tb-site-sidenav .mat-nav-list .mat-list-item.tb-active,
    .tb-site-sidenav .mat-mdc-list-item.active,
    .tb-site-sidenav .tb-active {
      background-color: #2B2F3A !important;
      color: #ffffff !important;
    }

    .tb-primary-toolbar button.mat-mdc-icon-button,
    .tb-primary-toolbar button.mat-mdc-icon-button .mat-icon,
    .tb-primary-toolbar .mat-icon,
    .tb-primary-toolbar .tb-user-display-name,
    .tb-primary-toolbar .tb-user-authority {
      color: #ffffff !important;
    }

    .tb-logo-title, .login-logo {
      width: 152px !important;
      height: 56px !important;
      display: block !important;
      flex-shrink: 0 !important;
    }
    .tb-logo-title img, .login-logo img {
      width: 100% !important;
      height: 100% !important;
      object-fit: contain !important;
    }
    .tb-powered-by-footer span a {
      pointer-events: auto !important;
    }
    tb-github-badge {
      display: none !important;
    }

    /* Hide Connect mobile app, Get started widgets, and broken widget error containers */
    tb-dashboard-widget:has(.tb-error-container),
    .tb-error-container,
    tb-mobile-app-qrcode-widget,
    .tb-mobile-app-qrcode-panel,
    tb-dashboard-widget:has(tb-mobile-app-qrcode-widget),
    tb-dashboard-widget:has(.tb-mobile-app-qrcode-panel),
    tb-dashboard-widget:has([title*="Connect mobile app"]),
    tb-dashboard-widget:has([title*="Download mobile app"]),
    tb-dashboard-widget:has([title*="Get started"]),
    tb-dashboard-widget:has([title*="Getting started"]),
    tb-dashboard-widget:has([title*="Select show mobile QR code"]),
    tb-dashboard-widget:has(img[alt*="App Store"]),
    tb-dashboard-widget:has(img[alt*="Google Play"]) {
      display: none !important;
    }

    /* Hide IoT Hub from Sidebar Menu */
    .tb-site-sidenav a[href*="iot-hub"],
    .tb-site-sidenav li:has(a[href*="iot-hub"]),
    .tb-site-sidenav tb-menu-link:has(a[href*="iot-hub"]),
    .tb-side-menu li:has(a[href*="iot-hub"]),
    .tb-side-menu li:has(.is-new),
    .tb-side-menu .is-new,
    a.is-new,
    li:has(a.is-new),
    a[href*="iot-hub"],
    li:has(a[href*="iot-hub"]) {
      display: none !important;
    }
"""

FLOATING_COPILOT_SNIPPET = r"""<!-- BEGIN FLOATING COPILOT -->
<style id="tb-fc-styles">
  #tb-fc-root {
    position: fixed;
    z-index: 999999;
    font-family: Roboto, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  }
  #tb-fc-fab {
    position: fixed;
    bottom: 26px;
    right: 26px;
    width: 58px;
    height: 58px;
    border-radius: 50%;
    background: linear-gradient(135deg, #1F232C 0%, #2B2F3A 55%, #0F766E 100%);
    box-shadow: 0 8px 24px rgba(15, 118, 110, 0.4), 0 4px 12px rgba(0, 0, 0, 0.25);
    border: 2px solid rgba(255, 255, 255, 0.25);
    display: none;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    transition: transform 0.25s cubic-bezier(0.16, 1, 0.3, 1), box-shadow 0.25s ease;
    z-index: 999999;
    outline: none;
    user-select: none;
  }
  #tb-fc-fab:hover {
    transform: scale(1.08) translateY(-2px);
    box-shadow: 0 12px 32px rgba(15, 118, 110, 0.55), 0 6px 16px rgba(0, 0, 0, 0.3);
  }
  #tb-fc-fab:active {
    transform: scale(0.96);
  }
  .tb-fc-fab-icon {
    display: flex;
    align-items: center;
    justify-content: center;
    color: #ffffff;
  }
  .tb-fc-fab-online {
    position: absolute;
    top: 2px;
    right: 2px;
    width: 13px;
    height: 13px;
    background-color: #10B981;
    border: 2.5px solid #1F232C;
    border-radius: 50%;
  }
  .tb-fc-fab-online::after {
    content: '';
    position: absolute;
    inset: -3px;
    border-radius: 50%;
    border: 2px solid #10B981;
    animation: tbFcPulse 2s cubic-bezier(0.24, 0, 0.38, 1) infinite;
  }
  @keyframes tbFcPulse {
    0% { transform: scale(0.8); opacity: 0.9; }
    70% { transform: scale(1.8); opacity: 0; }
    100% { transform: scale(1.8); opacity: 0; }
  }

  /* Chat Window Drawer */
  #tb-fc-window {
    position: fixed;
    bottom: 96px;
    right: 26px;
    width: 440px;
    height: 600px;
    max-width: calc(100vw - 32px);
    max-height: calc(100vh - 120px);
    background: #FFFFFF;
    border-radius: 20px;
    box-shadow: 0 24px 64px rgba(15, 23, 42, 0.28), 0 4px 20px rgba(0, 0, 0, 0.08), 0 0 0 1px rgba(0, 0, 0, 0.06);
    display: flex;
    flex-direction: column;
    overflow: hidden;
    z-index: 999999;
    transition: transform 0.28s cubic-bezier(0.16, 1, 0.3, 1), opacity 0.22s ease, visibility 0.22s;
  }
  #tb-fc-window.tb-fc-closed {
    opacity: 0;
    visibility: hidden;
    pointer-events: none;
    transform: translateY(24px) scale(0.95);
  }
  #tb-fc-window.tb-fc-open {
    opacity: 1;
    visibility: visible;
    pointer-events: auto;
    transform: translateY(0) scale(1);
  }

  /* Header */
  .tb-fc-header {
    background: #1F232C;
    padding: 14px 16px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    border-bottom: 1px solid rgba(255, 255, 255, 0.08);
    flex-shrink: 0;
  }
  .tb-fc-header-left {
    display: flex;
    align-items: center;
    gap: 10px;
  }
  .tb-fc-avatar-badge {
    width: 36px;
    height: 36px;
    border-radius: 10px;
    background: linear-gradient(135deg, #0F766E 0%, #14B8A6 100%);
    display: flex;
    align-items: center;
    justify-content: center;
    box-shadow: 0 2px 8px rgba(15, 118, 110, 0.35);
  }
  .tb-fc-title {
    color: #FFFFFF;
    font-size: 15px;
    font-weight: 600;
    letter-spacing: -0.2px;
  }
  .tb-fc-status {
    color: #94A3B8;
    font-size: 11px;
    display: flex;
    align-items: center;
    gap: 5px;
    margin-top: 1px;
  }
  .tb-fc-status-dot {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: #10B981;
  }
  .tb-fc-header-actions {
    display: flex;
    align-items: center;
    gap: 6px;
  }
  .tb-fc-btn-action {
    background: rgba(255, 255, 255, 0.08);
    border: none;
    color: #CBD5E1;
    border-radius: 8px;
    padding: 6px 10px;
    font-size: 12px;
    font-weight: 500;
    cursor: pointer;
    display: flex;
    align-items: center;
    gap: 4px;
    transition: all 0.2s;
  }
  .tb-fc-btn-action:hover {
    background: rgba(255, 255, 255, 0.16);
    color: #FFFFFF;
  }



  /* Thread */
  .tb-fc-thread {
    flex: 1;
    overflow-y: auto;
    padding: 14px 16px;
    display: flex;
    flex-direction: column;
    gap: 12px;
    background: #F8FAFC;
    scroll-behavior: smooth;
  }

  /* Welcome Screen */
  .tb-fc-welcome {
    margin: auto 0;
    text-align: center;
    padding: 12px 6px;
  }
  .tb-fc-welcome-icon {
    font-size: 32px;
    margin-bottom: 8px;
  }
  .tb-fc-welcome-title {
    font-size: 16px;
    font-weight: 700;
    color: #0F172A;
    margin-bottom: 6px;
  }
  .tb-fc-welcome-desc {
    font-size: 12.5px;
    color: #64748B;
    line-height: 1.5;
    margin-bottom: 16px;
  }
  .tb-fc-prompts-label {
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    color: #94A3B8;
    margin-bottom: 8px;
    text-align: left;
  }
  .tb-fc-prompts-grid {
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  .tb-fc-prompt-card {
    background: #FFFFFF;
    border: 1px solid #E2E8F0;
    border-radius: 10px;
    padding: 9px 12px;
    text-align: left;
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 12.5px;
    color: #1E293B;
    cursor: pointer;
    transition: all 0.2s;
  }
  .tb-fc-prompt-card:hover {
    border-color: #0F766E;
    background: #F0FDFA;
    transform: translateX(2px);
  }

  /* Rows */
  .tb-fc-row {
    display: flex;
    gap: 8px;
    align-items: flex-end;
    max-width: 90%;
    animation: tbFcRise 0.2s ease both;
  }
  .tb-fc-row-user {
    align-self: flex-end;
    flex-direction: row-reverse;
  }
  .tb-fc-row-assistant {
    align-self: flex-start;
  }
  .tb-fc-avatar {
    width: 26px;
    height: 26px;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 10px;
    font-weight: 700;
    flex-shrink: 0;
  }
  .tb-fc-row-user .tb-fc-avatar {
    background: #DBEAFE;
    color: #1D4ED8;
  }
  .tb-fc-row-assistant .tb-fc-avatar {
    background: #1F232C;
    color: #10B981;
  }
  .tb-fc-bubble {
    padding: 10px 14px;
    border-radius: 16px;
    font-size: 13px;
    line-height: 1.55;
    word-break: break-word;
  }
  .tb-fc-row-user .tb-fc-bubble {
    background: linear-gradient(135deg, #0F766E 0%, #0D9488 100%);
    color: #FFFFFF;
    border-bottom-right-radius: 4px;
    box-shadow: 0 2px 6px rgba(15, 118, 110, 0.25);
  }
  .tb-fc-row-assistant .tb-fc-bubble {
    background: #FFFFFF;
    color: #0F172A;
    border: 1px solid #E2E8F0;
    border-bottom-left-radius: 4px;
    box-shadow: 0 2px 6px rgba(0, 0, 0, 0.04);
  }
  .tb-fc-bubble strong { font-weight: 700; color: inherit; }
  .tb-fc-bubble em { font-style: italic; color: inherit; }
  .tb-fc-bubble ul, .tb-fc-bubble ol { margin: 6px 0; padding-left: 18px; }
  .tb-fc-bubble li { margin: 2px 0; }
  .tb-fc-time {
    font-size: 10px;
    color: #94A3B8;
    margin-top: 4px;
    text-align: right;
  }
  .tb-fc-row-assistant .tb-fc-time {
    text-align: left;
  }

  /* Typing */
  .tb-fc-typing {
    display: flex;
    align-items: center;
    gap: 4px;
    padding: 10px 14px;
    background: #FFFFFF;
    border: 1px solid #E2E8F0;
    border-radius: 14px;
    border-bottom-left-radius: 4px;
    width: fit-content;
  }
  .tb-fc-typing-dot {
    width: 6px;
    height: 6px;
    background: #0F766E;
    border-radius: 50%;
    animation: tbFcDot 1.4s infinite ease-in-out both;
  }
  .tb-fc-typing-dot:nth-child(1) { animation-delay: -0.32s; }
  .tb-fc-typing-dot:nth-child(2) { animation-delay: -0.16s; }
  .tb-fc-typing-label {
    font-size: 11.5px;
    color: #64748B;
    margin-left: 6px;
  }
  @keyframes tbFcDot {
    0%, 80%, 100% { transform: scale(0); opacity: 0.4; }
    40% { transform: scale(1); opacity: 1; }
  }
  @keyframes tbFcRise {
    from { opacity: 0; transform: translateY(6px); }
    to { opacity: 1; transform: none; }
  }

  /* Composer */
  .tb-fc-composer {
    background: #FFFFFF;
    border-top: 1px solid #E2E8F0;
    padding: 10px 14px;
    flex-shrink: 0;
  }
  .tb-fc-input-row {
    display: flex;
    gap: 8px;
    align-items: flex-end;
  }
  .tb-fc-input-row textarea {
    flex: 1;
    min-height: 42px;
    max-height: 96px;
    resize: none;
    border: 1px solid #CBD5E1;
    border-radius: 12px;
    padding: 10px 12px;
    font-size: 13px;
    line-height: 1.4;
    outline: none;
    box-sizing: border-box;
    font-family: inherit;
    color: #0F172A;
    background: #FFFFFF;
  }
  .tb-fc-input-row textarea:focus {
    border-color: #0F766E;
    box-shadow: 0 0 0 3px rgba(15, 118, 110, 0.15);
  }
  .tb-fc-send-btn {
    width: 42px;
    height: 42px;
    border-radius: 12px;
    background: linear-gradient(135deg, #0F766E 0%, #0D9488 100%);
    border: none;
    color: #FFFFFF;
    display: flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    flex-shrink: 0;
    transition: all 0.2s;
  }
  .tb-fc-send-btn:hover {
    transform: scale(1.05);
    box-shadow: 0 4px 12px rgba(15, 118, 110, 0.35);
  }
  .tb-fc-send-btn:disabled {
    opacity: 0.5;
    cursor: not-allowed;
    transform: none;
  }
  .tb-fc-hint {
    font-size: 10.5px;
    color: #94A3B8;
    margin-top: 6px;
    text-align: center;
  }
</style>

<div id="tb-fc-root">
  <button id="tb-fc-fab" title="Virtuoso AI Copilot" aria-label="Open AI Copilot">
    <div class="tb-fc-fab-icon">
      <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path>
        <path d="M12 7v2"></path>
        <path d="M12 13h.01"></path>
      </svg>
    </div>
    <span class="tb-fc-fab-online" title="Online"></span>
  </button>

  <div id="tb-fc-window" class="tb-fc-closed">
    <!-- Header -->
    <div class="tb-fc-header">
      <div class="tb-fc-header-left">
        <div class="tb-fc-avatar-badge">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#FFFFFF" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M12 2a2 2 0 0 1 2 2v2a2 2 0 0 1-2 2 2 2 0 0 1-2-2V4a2 2 0 0 1 2-2z"></path>
            <rect x="4" y="8" width="16" height="12" rx="3"></rect>
            <circle cx="9" cy="13" r="1.5" fill="#FFFFFF"></circle>
            <circle cx="15" cy="13" r="1.5" fill="#FFFFFF"></circle>
            <line x1="9" y1="17" x2="15" y2="17"></line>
          </svg>
        </div>
        <div class="tb-fc-header-info">
          <div class="tb-fc-title">Virtuoso AI Copilot</div>
          <div class="tb-fc-status"><span class="tb-fc-status-dot"></span> Delhivery Fleet Intelligence • 🟢 Online</div>
        </div>
      </div>
      <div class="tb-fc-header-actions">
        <button id="tb-fc-btn-reset" class="tb-fc-btn-action" title="Start New Conversation">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
            <polyline points="1 4 1 10 7 10"></polyline>
            <polyline points="23 20 23 14 17 14"></polyline>
            <path d="M20.49 9A9 9 0 0 0 5.64 5.64L1 10m22 4l-4.64 4.36A9 9 0 0 1 3.51 15"></path>
          </svg>
          <span>New</span>
        </button>
        <button id="tb-fc-btn-close" class="tb-fc-btn-action" title="Minimize">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
            <line x1="18" y1="6" x2="6" y2="18"></line>
            <line x1="6" y1="6" x2="18" y2="18"></line>
          </svg>
        </button>
      </div>
    </div>



    <!-- Message Thread -->
    <div class="tb-fc-thread" id="tb-fc-thread" role="log" aria-live="polite">
      <div class="tb-fc-welcome" id="tb-fc-welcome">
        <div class="tb-fc-welcome-icon">🤖</div>
        <div class="tb-fc-welcome-title">Delhivery Facility Copilot</div>
        <div class="tb-fc-welcome-desc">
          Ask in <strong>English or Hindi</strong> about generator telemetry, RO plant TDS & water quality, panel breakers, or active alarms.
        </div>
        <div class="tb-fc-prompts-label">Quick Actions:</div>
        <div class="tb-fc-prompts-grid">
          <button class="tb-fc-prompt-card" data-prompt="What is TDS right now ?">
            <span>💧</span>
            <span>What is TDS right now ?</span>
          </button>
          <button class="tb-fc-prompt-card" data-prompt="DG Set 1 live telemetry and alarms">
            <span>⚡</span>
            <span>DG Set 1 live status</span>
          </button>
          <button class="tb-fc-prompt-card" data-prompt="Are there any active alarms across Delhivery fleet?">
            <span>🚨</span>
            <span>Any active alarms?</span>
          </button>
          <button class="tb-fc-prompt-card" data-prompt="Sare devices ka summary status batao">
            <span>📊</span>
            <span>Sare devices ka summary do</span>
          </button>
        </div>
      </div>
    </div>

    <!-- Composer -->
    <div class="tb-fc-composer">
      <div class="tb-fc-input-row">
        <textarea id="tb-fc-input" rows="1" placeholder="Ask in English or Hindi (e.g. What is TDS right now?)..."></textarea>
        <button type="button" id="tb-fc-send" title="Send (Enter)" class="tb-fc-send-btn">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
            <line x1="22" y1="2" x2="11" y2="13"></line>
            <polygon points="22 2 15 22 11 13 2 9 22 2"></polygon>
          </svg>
        </button>
      </div>
      <div class="tb-fc-hint">Press <strong>Enter</strong> to send • <strong>Shift+Enter</strong> for newline</div>
    </div>
  </div>
</div>

<script id="tb-fc-script">
(function() {
  var STORAGE_KEY = 'tb_floating_copilot_v2';
  var devices = [];
  var state = {
    isOpen: false,
    busy: false,
    conversationId: null,
    selectedDeviceId: null,
    selectedDeviceName: null,
    messages: []
  };

  function getAuthToken() {
    return localStorage.getItem('jwt_token') || '';
  }

  function generateUUID() {
    if (typeof crypto !== 'undefined' && crypto.randomUUID) {
      return crypto.randomUUID();
    }
    return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function(c) {
      var r = Math.random() * 16 | 0, v = c === 'x' ? r : (r & 0x3 | 0x8);
      return v.toString(16);
    });
  }

  function loadState() {
    try {
      var s = JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}');
      state.conversationId = s.conversationId || generateUUID();
      state.selectedDeviceId = s.selectedDeviceId || null;
      state.selectedDeviceName = s.selectedDeviceName || null;
      state.messages = Array.isArray(s.messages) ? s.messages : [];
    } catch(e) {
      state.conversationId = generateUUID();
      state.selectedDeviceId = null;
      state.selectedDeviceName = null;
      state.messages = [];
    }
  }

  function saveState() {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify({
        conversationId: state.conversationId,
        selectedDeviceId: state.selectedDeviceId,
        selectedDeviceName: state.selectedDeviceName,
        messages: state.messages.slice(-10)
      }));
    } catch(e) {}
  }

  function updateVisibility() {
    var fab = document.getElementById('tb-fc-fab');
    var win = document.getElementById('tb-fc-window');
    if (!fab || !win) return;
    var token = getAuthToken();
    var isLoginPage = window.location.pathname.indexOf('/login') !== -1;
    if (!token || isLoginPage) {
      fab.style.display = 'none';
      win.classList.remove('tb-fc-open');
      win.classList.add('tb-fc-closed');
      state.isOpen = false;
    } else {
      fab.style.display = 'flex';
    }
  }

  function toggleWindow(open) {
    var win = document.getElementById('tb-fc-window');
    if (!win) return;
    if (typeof open === 'boolean') {
      state.isOpen = open;
    } else {
      state.isOpen = !state.isOpen;
    }
    if (state.isOpen) {
      win.classList.remove('tb-fc-closed');
      win.classList.add('tb-fc-open');
      var inp = document.getElementById('tb-fc-input');
      if (inp) setTimeout(function() { inp.focus(); }, 150);
      scrollThread();
      loadDevices();
    } else {
      win.classList.remove('tb-fc-open');
      win.classList.add('tb-fc-closed');
    }
  }

  function formatMarkdown(text) {
    var s = String(text || '');
    s = s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    s = s.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
    s = s.replace(/(^|[^*])\*([^*]+)\*(?!\*)/g, '$1<em>$2</em>');
    s = s.replace(/^### (.*$)/gim, '<div style="font-weight:700;font-size:13.5px;margin:6px 0 2px;">$1</div>');
    s = s.replace(/^## (.*$)/gim, '<div style="font-weight:700;font-size:14px;margin:8px 0 3px;">$1</div>');
    s = s.replace(/^# (.*$)/gim, '<div style="font-weight:700;font-size:15px;margin:10px 0 4px;">$1</div>');
    
    var lines = s.split('\n');
    var inList = false;
    var out = [];
    for (var i = 0; i < lines.length; i++) {
      var line = lines[i];
      var m = line.match(/^\s*[-*•]\s+(.*)$/);
      if (m) {
        if (!inList) { out.push('<ul>'); inList = true; }
        out.push('<li>' + m[1] + '</li>');
      } else {
        if (inList) { out.push('</ul>'); inList = false; }
        out.push(line);
      }
    }
    if (inList) out.push('</ul>');
    s = out.join('\n');
    s = s.replace(/\n\n+/g, '<br><br>');
    s = s.replace(/\n(?![<])/g, '<br>');
    return s;
  }

  function scrollThread() {
    var thread = document.getElementById('tb-fc-thread');
    if (thread) {
      setTimeout(function() { thread.scrollTop = thread.scrollHeight; }, 50);
    }
  }

  function getCurrentDashboardId() {
    try {
      var full = (window.location.pathname || '') + ' ' + (window.location.hash || '');
      var m = full.match(/dashboards?\/([a-f0-9\-]{36})/i);
      if (m) return m[1];
    } catch(e) {}
    return null;
  }

  function renderThread() {
    var thread = document.getElementById('tb-fc-thread');
    var welcome = document.getElementById('tb-fc-welcome');
    if (!thread) return;

    if (!state.messages || state.messages.length === 0) {
      thread.innerHTML = '';
      if (welcome) thread.appendChild(welcome);
      return;
    }

    thread.innerHTML = '';
    for (var i = 0; i < state.messages.length; i++) {
      var msg = state.messages[i];
      appendBubbleDOM(msg.role, msg.content, msg.time);
    }
    scrollThread();
  }

  function appendBubbleDOM(role, text, timeStr) {
    var thread = document.getElementById('tb-fc-thread');
    if (!thread) return;

    var row = document.createElement('div');
    row.className = 'tb-fc-row tb-fc-row-' + (role === 'USER' ? 'user' : 'assistant');

    var avatar = document.createElement('div');
    avatar.className = 'tb-fc-avatar';
    avatar.textContent = role === 'USER' ? 'OP' : 'AI';

    var bubbleWrap = document.createElement('div');
    bubbleWrap.style.display = 'flex';
    bubbleWrap.style.flexDirection = 'column';

    var bubble = document.createElement('div');
    bubble.className = 'tb-fc-bubble';
    bubble.innerHTML = formatMarkdown(text);
    bubbleWrap.appendChild(bubble);

    if (timeStr) {
      var t = document.createElement('div');
      t.className = 'tb-fc-time';
      t.textContent = timeStr;
      bubbleWrap.appendChild(t);
    }

    row.appendChild(avatar);
    row.appendChild(bubbleWrap);
    thread.appendChild(row);
    scrollThread();
  }

  function showTypingIndicator() {
    var thread = document.getElementById('tb-fc-thread');
    if (!thread) return;
    var existing = document.getElementById('tb-fc-typing-indicator');
    if (existing) existing.remove();

    var typing = document.createElement('div');
    typing.id = 'tb-fc-typing-indicator';
    typing.className = 'tb-fc-typing';
    typing.innerHTML = '<div class="tb-fc-typing-dot"></div><div class="tb-fc-typing-dot"></div><div class="tb-fc-typing-dot"></div><span class="tb-fc-typing-label">Analyzing live telemetry...</span>';
    thread.appendChild(typing);
    scrollThread();
  }

  function removeTypingIndicator() {
    var el = document.getElementById('tb-fc-typing-indicator');
    if (el) el.remove();
  }

  function getCopilotBaseUrl() {
    if (window.TB_COPILOT_BASE_URL) return window.TB_COPILOT_BASE_URL;
    if (window.location.port === '9091') {
      return window.location.protocol + '//' + window.location.hostname + ':8097';
    }
    return window.location.origin + '/copilot';
  }

  async function loadDevices() {
    var token = getAuthToken();
    if (!token) return;
    try {
      var res = await fetch(getCopilotBaseUrl() + '/v1/devices', {
        headers: { 'X-Authorization': 'Bearer ' + token }
      });
      if (res.ok) {
        devices = await res.json();
      }
    } catch(e) {}
  }

  async function sendQuery(text) {
    var q = String(text || '').trim();
    if (!q || state.busy) return;

    var timeNow = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    appendBubbleDOM('USER', q, timeNow);
    state.messages.push({ role: 'USER', content: q, time: timeNow });
    saveState();

    var inp = document.getElementById('tb-fc-input');
    if (inp) inp.value = '';

    state.busy = true;
    var sendBtn = document.getElementById('tb-fc-send');
    if (sendBtn) sendBtn.disabled = true;
    showTypingIndicator();

    try {
      var token = getAuthToken();
      var historyClean = (state.messages || []).slice(-8).map(function(m) {
        return { role: m.role, content: m.content };
      });
      var payload = {
        message: q,
        conversationId: state.conversationId,
        messages: historyClean
      };
      var activeDashId = getCurrentDashboardId();
      if (activeDashId) {
        payload.dashboardId = activeDashId;
      }
      var res = await fetch(getCopilotBaseUrl() + '/v1/chat', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Authorization': 'Bearer ' + token
        },
        body: JSON.stringify(payload)
      });
      if (!res.ok) throw new Error('HTTP ' + res.status);
      var data = await res.json();

      removeTypingIndicator();
      var answer = data.answer || 'No response received from copilot.';
      if (data.resolvedDevice && data.resolvedDevice.id) {
        state.selectedDeviceId = data.resolvedDevice.id;
        state.selectedDeviceName = data.resolvedDevice.name;
      }
      if (data.conversationId) {
        state.conversationId = data.conversationId;
      }

      var botTime = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
      appendBubbleDOM('ASSISTANT', answer, botTime);
      state.messages.push({ role: 'ASSISTANT', content: answer, time: botTime });
      saveState();
    } catch(err) {
      removeTypingIndicator();
      var errMsg = 'Unable to connect to Copilot service. Please verify your connection or retry in a moment.';
      appendBubbleDOM('ASSISTANT', errMsg, '');
    } finally {
      state.busy = false;
      if (sendBtn) sendBtn.disabled = false;
      if (inp) inp.focus();
    }
  }

  function initEvents() {
    var fab = document.getElementById('tb-fc-fab');
    if (fab) fab.addEventListener('click', function() { toggleWindow(); });

    var closeBtn = document.getElementById('tb-fc-btn-close');
    if (closeBtn) closeBtn.addEventListener('click', function() { toggleWindow(false); });

    var resetBtn = document.getElementById('tb-fc-btn-reset');
    if (resetBtn) resetBtn.addEventListener('click', function() {
      state.conversationId = generateUUID();
      state.selectedDeviceId = null;
      state.selectedDeviceName = null;
      state.messages = [];
      localStorage.removeItem(STORAGE_KEY);
      renderThread();
    });

    var sendBtn = document.getElementById('tb-fc-send');
    var inp = document.getElementById('tb-fc-input');
    if (sendBtn && inp) {
      sendBtn.addEventListener('click', function() {
        sendQuery(inp.value);
      });
      inp.addEventListener('keydown', function(e) {
        if (e.key === 'Enter' && !e.shiftKey) {
          e.preventDefault();
          sendQuery(inp.value);
        }
      });
    }

    // Quick prompt cards delegation
    document.addEventListener('click', function(e) {
      var card = e.target.closest('.tb-fc-prompt-card');
      if (card) {
        var p = card.getAttribute('data-prompt');
        if (p) sendQuery(p);
      }
    });

    // Check visibility on navigation
    window.addEventListener('popstate', updateVisibility);
    setInterval(updateVisibility, 1500);
    var obs = new MutationObserver(updateVisibility);
    obs.observe(document.body, { childList: true, subtree: true });
  }

  loadState();
  initEvents();
  updateVisibility();
  renderThread();
  loadDevices();
})();
</script>
<!-- END FLOATING COPILOT -->
"""

SSO_REDIRECT_JS = """
  <script>
    (function() {
      var isLoggingOut = false;

      function doKeycloakLogout() {
        try {
          localStorage.clear();
          sessionStorage.clear();
          var f = document.createElement("form");
          f.method = "POST";
          f.action = "https://auth.virtuosonetsoft.variphi.com/realms/viot/protocol/openid-connect/logout";
          var c = document.createElement("input"); c.type = "hidden"; c.name = "client_id"; c.value = "viot"; f.appendChild(c);
          var r = document.createElement("input"); r.type = "hidden"; r.name = "post_logout_redirect_uri"; r.value = window.location.origin + "/login"; f.appendChild(r);
          document.body.appendChild(f);
          f.submit();
        } catch(e) {
          console.error("SSO logout error", e);
        }
      }

      window.triggerKeycloakLogout = doKeycloakLogout;

      // Listen for click on logout menu item / button
      document.addEventListener("click", function(e) {
        var el = e.target && e.target.closest ? e.target.closest("button, a, mat-list-item, [role='menuitem']") : null;
        if (el) {
          var txt = (el.innerText || "").trim().toLowerCase();
          if (txt.includes("log out") || txt.includes("logout")) {
            isLoggingOut = true;
          }
        }
      }, true);

      // Intercept XHR to /api/auth/logout
      var origOpen = XMLHttpRequest.prototype.open;
      XMLHttpRequest.prototype.open = function(method, url) {
        if (url && (url === "/api/auth/logout" || (typeof url === "string" && url.indexOf("/api/auth/logout") !== -1))) {
          isLoggingOut = true;
          this.addEventListener("loadend", function() {
            setTimeout(doKeycloakLogout, 50);
          });
        }
        return origOpen.apply(this, arguments);
      };

      function checkLogin() {
        if (isLoggingOut) {
          doKeycloakLogout();
          return;
        }
        if (window.location.pathname === '/login' && 
            !window.location.search.includes('localLogin=true') && 
            !window.location.search.includes('accessToken') && 
            !window.location.search.includes('loginError')) {
          window.location.replace('/oauth2/authorization/68b2bc20-5e98-11f1-bade-0bee8153e08f');
        }
      }

      checkLogin();
      window.addEventListener('popstate', checkLogin);
      var lastPath = location.pathname;
      var obs = new MutationObserver(function() {
        if (location.pathname !== lastPath) {
          lastPath = location.pathname;
          checkLogin();
        }
      });
      obs.observe(document, {subtree: true, childList: true});
    })();
  </script>
"""

def main():
    print("==> 1. Copying Virtuoso branding assets")
    shutil.copy2(f"{BRANDING_DIR}/assets/logo_title_white.svg", f"{PUBLIC_DIR}/assets/logo_title_white.svg")
    shutil.copy2(f"{BRANDING_DIR}/assets/logo_white.svg", f"{PUBLIC_DIR}/assets/logo_white.svg")
    shutil.copy2(f"{BRANDING_DIR}/assets/virtuoso-favicon.png", f"{PUBLIC_DIR}/assets/virtuoso-favicon.png")
    shutil.copy2(f"{BRANDING_DIR}/assets/virtuoso-logo.png", f"{PUBLIC_DIR}/assets/virtuoso-logo.png")
    shutil.copy2(f"{BRANDING_DIR}/assets/virtuoso-favicon.ico", f"{PUBLIC_DIR}/thingsboard.ico")

    print("==> 2. Patching index.html")
    index_path = f"{PUBLIC_DIR}/index.html"
    with open(index_path, 'r', encoding='utf-8') as f:
        html = f.read()

    # Title
    html = html.replace("<title>ThingsBoard</title>", "<title>Virtuoso NetSoft</title>")

    # Clean and inject updated theme styles
    import re
    html = re.sub(r'<style type="text/css">\s*/\* Virtuoso NetSoft Dark Charcoal Theme.*?</style>\s*', '', html, flags=re.DOTALL)
    html = html.replace("</head>", f"<style type=\"text/css\">{DARK_CHARCOAL_CSS}</style>\n</head>")

    # Clean previous SSO scripts and inject updated SSO_REDIRECT_JS with logout handler
    html = re.sub(r'<!-- BEGIN FLOATING COPILOT -->.*?<!-- END FLOATING COPILOT -->', '', html, flags=re.DOTALL)
    html = html.replace("</body>", f"{FLOATING_COPILOT_SNIPPET.strip()}\n{SSO_REDIRECT_JS.strip()}\n</body>")

    if 'virtuoso-favicon.png' not in html:
        html = html.replace('<link rel="icon" type="image/x-icon" href="thingsboard.ico">',
                            '<link rel="icon" type="image/x-icon" href="thingsboard.ico">\n  <link rel="icon" type="image/png" href="assets/virtuoso-favicon.png">')

    with open(index_path, 'w', encoding='utf-8') as f:
        f.write(html)
    print("    index.html patched with Dark Charcoal Theme, Connect mobile app hide, and SSO logout/auto-redirect")

    print("==> 3. Patching styles-WUQVJSVC.css")
    css_path = f"{PUBLIC_DIR}/styles-WUQVJSVC.css"
    if os.path.exists(css_path):
        with open(css_path, 'r', encoding='utf-8') as f:
            css = f.read()
        css = re.sub(r'/\* Virtuoso NetSoft Dark Charcoal Theme.*', '', css, flags=re.DOTALL)
        css += f"\n{DARK_CHARCOAL_CSS}\n"
        with open(css_path, 'w', encoding='utf-8') as f:
            f.write(css)
        print("    styles-WUQVJSVC.css updated with Dark Charcoal theme and mobile app hide overrides")

    print("==> 4. Patching chunk-AWADN7CA.js (appTitle & remove IoT Hub from sidebar)")
    aw_path = f"{PUBLIC_DIR}/chunk-AWADN7CA.js"
    if os.path.exists(aw_path):
        with open(aw_path, 'r', encoding='utf-8') as f:
            js = f.read()
        changed = False
        if 'appTitle:"ThingsBoard"' in js:
            js = js.replace('appTitle:"ThingsBoard"', 'appTitle:"Virtuoso NetSoft"')
            changed = True
        if ',{id:te.iot_hub}' in js:
            js = js.replace(',{id:te.iot_hub}', '')
            changed = True
        elif '{id:te.iot_hub},' in js:
            js = js.replace('{id:te.iot_hub},', '')
            changed = True
        if changed:
            with open(aw_path, 'w', encoding='utf-8') as f:
                f.write(js)
            with open(aw_path, 'rb') as f_in, gzip.open(f"{aw_path}.gz", 'wb', compresslevel=9) as f_out:
                shutil.copyfileobj(f_in, f_out)
            print("    chunk-AWADN7CA.js patched & re-gzipped (appTitle + IoT Hub removed from menu)")

    print("==> 5. Patching chunk-QBQ4XMPH.js (Powered by & links)")
    qb_path = f"{PUBLIC_DIR}/chunk-QBQ4XMPH.js"
    if os.path.exists(qb_path):
        with open(qb_path, 'r', encoding='utf-8') as f:
            js = f.read()
        changed = False
        if 'ThingsBoard v.' in js:
            js = js.replace('ThingsBoard v.', 'Virtuoso NetSoft v.')
            changed = True
        if '["href","https://thingsboard.io","target","_blank"]' in js:
            js = js.replace('["href","https://thingsboard.io","target","_blank"]', '["href","https://virtuosonetsoft.com","target","_blank"]')
            changed = True
        if changed:
            with open(qb_path, 'w', encoding='utf-8') as f:
                f.write(js)
            with open(qb_path, 'rb') as f_in, gzip.open(f"{qb_path}.gz", 'wb', compresslevel=9) as f_out:
                shutil.copyfileobj(f_in, f_out)
            print("    chunk-QBQ4XMPH.js patched & re-gzipped")

    print("==> 6. Patching main-RUDBBS27.js (login logo link & title)")
    main_path = f"{PUBLIC_DIR}/main-RUDBBS27.js"
    if os.path.exists(main_path):
        with open(main_path, 'r', encoding='utf-8') as f:
            js = f.read()
        changed = False
        if '["link","https://thingsboard.io","target","_blank",1,"login-logo"]' in js:
            js = js.replace('["link","https://thingsboard.io","target","_blank",1,"login-logo"]', '["link","https://virtuosonetsoft.com","target","_blank",1,"login-logo"]')
            changed = True
        if 'console.log(`ThingsBoard Version:' in js:
            js = js.replace('console.log(`ThingsBoard Version:', 'console.log(`Virtuoso NetSoft Version:')
            changed = True
        if changed:
            with open(main_path, 'w', encoding='utf-8') as f:
                f.write(js)
            with open(main_path, 'rb') as f_in, gzip.open(f"{main_path}.gz", 'wb', compresslevel=9) as f_out:
                shutil.copyfileobj(f_in, f_out)
            print("    main-RUDBBS27.js patched & re-gzipped")

    print("==> 7. Patching home page dashboard templates (remove broken IoT Hub & Get started, re-layout to full width)")
    import json
    
    # 7a. Tenant Admin Home Page
    dash_path = f"{PUBLIC_DIR}/assets/dashboard/tenant_admin_home_page.json"
    if os.path.exists(dash_path):
        with open(dash_path, 'r', encoding='utf-8') as f:
            d = json.load(f)

        to_remove = set()
        for wid, w in d.get('configuration', {}).get('widgets', {}).items():
            title = str(w.get('config', {}).get('title', ''))
            fqn = str(w.get('typeFullFqn', ''))
            if ('iot_hub' in fqn or 'IoT Hub' in title or 
                'getting_started' in fqn or 'Getting started' in title or 
                'Select show mobile' in title or 'mobile-app' in title or 'mobile_app' in fqn):
                to_remove.add(wid)

        for wid in to_remove:
            d['configuration']['widgets'].pop(wid, None)
            print(f"    Removed widget {wid} from tenant_admin_home_page.json")

        states = d.get('configuration', {}).get('states', {})
        if 'mobile_app_qr_code' in states:
            del states['mobile_app_qr_code']

        if 'default' in states and 'main' in states['default'].get('layouts', {}):
            main_widgets = states['default']['layouts']['main'].get('widgets', {})
            for wid in list(main_widgets.keys()):
                if wid in to_remove:
                    del main_widgets[wid]

            # Re-layout remaining 7 widgets across 120 columns seamlessly
            layout_map = {
                '35d3ac3b-f1af-dc3d-a1d1-11f351d16fc6': {'col': 0, 'row': 0, 'sizeX': 60, 'sizeY': 12},   # Devices
                '7ac20b6a-dc40-b18e-9f5f-bca20bc693bb': {'col': 60, 'row': 0, 'sizeX': 60, 'sizeY': 12},  # Alarms
                '6d6e2b1d-6ce7-4678-3745-c6b0897b2674': {'col': 0, 'row': 12, 'sizeX': 60, 'sizeY': 17},  # Dashboards
                'd70cc256-4c7b-ee06-9905-b8c5e546605f': {'col': 60, 'row': 12, 'sizeX': 60, 'sizeY': 17}, # Activity / Transport messages
                '9e3ef045-d8bc-1640-a3f4-2dd10b19d50e': {'col': 0, 'row': 29, 'sizeX': 40, 'sizeY': 14},   # Quick links
                '867f82cf-ecf2-2d5c-35cb-08c6f2edc3a4': {'col': 40, 'row': 29, 'sizeX': 40, 'sizeY': 14},  # Documentation
                'ebbd0a6e-8a47-e770-5086-7f4974250f2d': {'col': 80, 'row': 29, 'sizeX': 40, 'sizeY': 14},  # Usage info
            }
            for wid, pos in layout_map.items():
                if wid in main_widgets:
                    main_widgets[wid].update(pos)

        with open(dash_path, 'w', encoding='utf-8') as f:
            json.dump(d, f)
        print("    tenant_admin_home_page.json cleaned and re-layouted to full 120-col width")

    # 7b. Sys Admin Home Page
    sys_path = f"{PUBLIC_DIR}/assets/dashboard/sys_admin_home_page.json"
    if os.path.exists(sys_path):
        with open(sys_path, 'r', encoding='utf-8') as f:
            d = json.load(f)

        to_remove = set()
        for wid, w in d.get('configuration', {}).get('widgets', {}).items():
            title = str(w.get('config', {}).get('title', ''))
            fqn = str(w.get('typeFullFqn', ''))
            if ('getting_started' in fqn or 'Getting started' in title or 
                'Select show mobile' in title or 'mobile-app' in title or 'mobile_app' in fqn):
                to_remove.add(wid)

        for wid in to_remove:
            d['configuration']['widgets'].pop(wid, None)
            print(f"    Removed widget {wid} from sys_admin_home_page.json")

        states = d.get('configuration', {}).get('states', {})
        if 'mobile_app_qr_code' in states:
            del states['mobile_app_qr_code']

        if 'default' in states and 'main' in states['default'].get('layouts', {}):
            main_widgets = states['default']['layouts']['main'].get('widgets', {})
            for wid in list(main_widgets.keys()):
                if wid in to_remove:
                    del main_widgets[wid]

            sys_layout_map = {
                '163025d8-3ca4-dd1e-c17b-e40d8e03e8a8': {'col': 0, 'row': 0, 'sizeX': 60, 'sizeY': 15},   # Entities info cards
                '4b5e47ed-c197-a937-d727-041ba8decec2': {'col': 60, 'row': 0, 'sizeX': 60, 'sizeY': 26},  # System info
                '867f82cf-ecf2-2d5c-35cb-08c6f2edc3a4': {'col': 0, 'row': 15, 'sizeX': 60, 'sizeY': 14},  # Documentation
                'd70cc256-4c7b-ee06-9905-b8c5e546605f': {'col': 60, 'row': 26, 'sizeX': 60, 'sizeY': 16}, # Transport messages
                'd2784f6c-0518-fd95-1d28-b21f70bdcb10': {'col': 0, 'row': 29, 'sizeX': 60, 'sizeY': 13},  # Configured features
                '66dcf1a2-9d83-6873-c693-d6a5d989b3f8': {'col': 0, 'row': 42, 'sizeX': 40, 'sizeY': 16},  # Version
                '8acbf5df-f9fc-114d-216f-86f081aa4779': {'col': 40, 'row': 42, 'sizeX': 80, 'sizeY': 16}, # Functions
            }
            for wid, pos in sys_layout_map.items():
                if wid in main_widgets:
                    main_widgets[wid].update(pos)

        with open(sys_path, 'w', encoding='utf-8') as f:
            json.dump(d, f)
        print("    sys_admin_home_page.json cleaned and re-layouted to full 120-col width")

    print("==> 8. Patching chunk-3WMNFA25.js (Keycloak SSO Logout)")
    chunk_path = f"{PUBLIC_DIR}/chunk-3WMNFA25.js"
    if os.path.exists(chunk_path):
        with open(chunk_path, 'r', encoding='utf-8') as f:
            js = f.read()
        target = 'logout(i=!1,n=!1){i&&(this.redirectUrl=this.router.url),n?this.clearJwtToken():this.http.post("/api/auth/logout",null,vt(!0,!0)).subscribe(()=>{this.clearJwtToken()},()=>{this.clearJwtToken()})}'
        replacement = 'logout(i=!1,n=!1){i&&(this.redirectUrl=this.router.url);try{if(window.triggerKeycloakLogout){this.clearJwtToken();window.triggerKeycloakLogout();return;}var _f=document.createElement("form");_f.method="POST";_f.action="https://auth.virtuosonetsoft.variphi.com/realms/viot/protocol/openid-connect/logout";var _c=document.createElement("input");_c.type="hidden";_c.name="client_id";_c.value="viot";_f.appendChild(_c);var _r=document.createElement("input");_r.type="hidden";_r.name="post_logout_redirect_uri";_r.value=window.location.origin+"/login";_f.appendChild(_r);document.body.appendChild(_f);this.clearJwtToken();_f.submit();return;}catch(e){}n?this.clearJwtToken():this.http.post("/api/auth/logout",null,vt(!0,!0)).subscribe(()=>{this.clearJwtToken()},()=>{this.clearJwtToken()})}'
        if target in js:
            js = js.replace(target, replacement)
            with open(chunk_path, 'w', encoding='utf-8') as f:
                f.write(js)
            with open(chunk_path, 'rb') as f_in, gzip.open(f"{chunk_path}.gz", 'wb', compresslevel=9) as f_out:
                shutil.copyfileobj(f_in, f_out)
            print("    chunk-3WMNFA25.js patched with Keycloak SSO logout & re-gzipped")
        elif 'triggerKeycloakLogout' in js:
            print("    chunk-3WMNFA25.js already patched with Keycloak SSO logout")
        else:
            print("    WARNING: target logout signature not found in chunk-3WMNFA25.js")

    print("==> DONE patching public UI files")

if __name__ == '__main__':
    main()
