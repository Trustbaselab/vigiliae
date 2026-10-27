# -*- coding: utf-8 -*-
"""Phone-friendly token auth.

Why not HTTP Basic Auth? WeChat's in-app browser and several mobile browsers
do not show the Basic Auth prompt, so a token in the URL (then a cookie) is the
most reliable lowest-common-denominator login for a personal bot.

Security notes:
  * the token is read from the BOT_TOKEN environment variable;
  * comparison is constant-time;
  * the cookie is HttpOnly, SameSite=Lax;
  * if BOT_TOKEN is unset the app runs open (dev mode) and warns loudly.
"""
import hmac

from . import config

PUBLIC_PATHS = {"/login", "/logout", "/api/heartbeat", "/api/health"}

_token_holder = {"v": config.BOT_TOKEN}


def set_bot_token(token):
    _token_holder["v"] = token or ""


def get_bot_token():
    return _token_holder["v"]


def token_ok(token):
    expected = _token_holder["v"]
    if not expected or not token:
        return False
    return hmac.compare_digest(str(token), str(expected))


LOGIN_PAGE = """<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=3,user-scalable=yes">
<title>Vigiliae · Sign in</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{background:#0A0A0F;color:#FAFAFA;font-family:-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;
     min-height:100vh;display:flex;align-items:center;justify-content:center;padding:24px;font-size:17px}
.box{width:100%;max-width:420px;background:#131318;border:1px solid #26262F;border-radius:16px;padding:28px 24px}
h1{font-size:24px;margin-bottom:8px}
.sub{color:#8A8A94;font-size:15px;margin-bottom:24px;line-height:1.6}
label{display:block;font-size:15px;color:#C4C4CE;margin-bottom:8px}
input{width:100%;background:#1C1C24;border:1px solid #26262F;border-radius:11px;
      padding:15px 17px;color:#FAFAFA;font-size:17px;font-family:inherit}
input:focus{outline:none;border-color:#FF4F9A}
button{width:100%;margin-top:16px;background:#FF4F9A;color:#0A0A0F;border:none;border-radius:11px;
       padding:16px;font-size:18px;font-weight:700;font-family:inherit}
button:active{opacity:.7}
.err{color:#EF4444;font-size:15px;margin-top:14px;line-height:1.6;display:none}
.tip{margin-top:22px;padding-top:18px;border-top:1px solid #26262F;color:#55555F;font-size:14px;line-height:1.7}
</style></head><body>
<div class="box">
  <h1>Vigiliae</h1>
  <div class="sub">Enter your access token. You only need to do this once per device; the cookie lasts 30 days.</div>
  <form method="get" action="/login">
    <label>Access token</label>
    <input type="password" name="k" placeholder="bot-..." autofocus autocomplete="off">
    <button type="submit">Continue</button>
  </form>
  <div class="err" id="e">Wrong token. Try again.</div>
  <div class="tip">The token is the value of BOT_TOKEN in your .env file. Keep it private.</div>
</div>
<script>
if (location.search.indexOf('bad=1') >= 0) document.getElementById('e').style.display='block';
</script>
</body></html>"""
