/*
  Lazii-Bot overlay - a chubby, slightly grungy couch-bot mascot with a chat
  box that talks to the local LLM and can change the bot's settings for you.

  Self-contained: injects its own CSS and DOM. Drop this script on any page of
  the control panel. The chat calls POST /api/chat; when the backend applies
  settings it also emits window event "lazii:config-changed" so forms refresh.
*/
(function () {
    'use strict';

    var CSS = [
        '#lazii-root { position: fixed; right: 18px; bottom: 0; z-index: 9999; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; }',
        '#lazii-root * { box-sizing: border-box; }',

        /* --- launcher bubble --- */
        '.lazii-bubble { position: relative; margin-left: auto; width: 76px; height: 76px; border: none; background: none; padding: 0; cursor: pointer; display: block; margin-bottom: 2px; }',
        '.lazii-bubble:hover .lazii-svg { transform: translateY(-3px) scale(1.03); }',
        '.lazii-bubble .lazii-tip { position: absolute; right: 82px; bottom: 26px; white-space: nowrap; background: #141b26; color: #e8e2d6; font-size: 12px; padding: 6px 10px; border-radius: 8px; opacity: 0; pointer-events: none; transition: opacity .2s; border: 1px solid #2b3648; }',
        '.lazii-bubble:hover .lazii-tip { opacity: 1; }',

        /* --- mascot --- */
        '.lazii-svg { width: 100%; height: 100%; display: block; transform-origin: 50% 90%; transition: transform .25s ease; animation: lazii-bob 3.4s ease-in-out infinite; filter: drop-shadow(0 6px 10px rgba(0,0,0,.45)); }',
        '@keyframes lazii-bob { 0%,100% { transform: translateY(0); } 50% { transform: translateY(-4px); } }',
        '.lazii-eye { animation: lazii-blink 5.2s infinite; transform-origin: center; }',
        '@keyframes lazii-blink { 0%, 92%, 100% { transform: scaleY(1); } 95% { transform: scaleY(.08); } }',
        '.lazii-zzz { animation: lazii-zzz 4s ease-in-out infinite; opacity: 0; }',
        '.lazii-zzz.z2 { animation-delay: 1.3s; } .lazii-zzz.z3 { animation-delay: 2.6s; }',
        '@keyframes lazii-zzz { 0% { opacity: 0; transform: translate(0,0); } 25% { opacity: .9; } 100% { opacity: 0; transform: translate(10px,-16px); } }',
        '.lazii-wobble .lazii-svg { animation: lazii-wobble .55s ease; }',
        '@keyframes lazii-wobble { 0% { transform: rotate(0); } 25% { transform: rotate(-6deg) scale(1.04); } 55% { transform: rotate(5deg); } 100% { transform: rotate(0); } }',
        '.lazii-think .lazii-svg { animation: lazii-think .9s ease-in-out infinite; }',
        '@keyframes lazii-think { 0%,100% { transform: translateY(0) rotate(-2deg); } 50% { transform: translateY(-7px) rotate(2deg); } }',

        /* --- chat panel (docked to the bottom) --- */
        '.lazii-panel { width: 360px; max-width: calc(100vw - 36px); height: 460px; max-height: 70vh; background: #141b26; color: #e8e2d6; border: 1px solid #2b3648; border-bottom: none; border-radius: 14px 14px 0 0; box-shadow: 0 -8px 30px rgba(0,0,0,.5); display: none; flex-direction: column; overflow: hidden; animation: lazii-rise .25s ease; }',
        '@keyframes lazii-rise { from { transform: translateY(30px); opacity: 0; } to { transform: translateY(0); opacity: 1; } }',
        '.lazii-root.open .lazii-panel { display: flex; }',
        '.lazii-root.open .lazii-bubble { position: absolute; right: 6px; bottom: 470px; width: 58px; height: 58px; margin: 0; }',
        '.lazii-head { display: flex; align-items: center; gap: 10px; padding: 10px 14px; background: #0f1520; border-bottom: 1px solid #2b3648; }',
        '.lazii-head .lazii-mini { width: 34px; height: 34px; flex: none; }',
        '.lazii-head .lazii-title { font-weight: 700; font-size: 14px; }',
        '.lazii-head .lazii-sub { font-size: 11.5px; color: #8fa0b8; }',
        '.lazii-head button { margin-left: auto; background: none; border: none; color: #8fa0b8; font-size: 18px; cursor: pointer; padding: 4px 8px; border-radius: 6px; }',
        '.lazii-head button:hover { color: #e8e2d6; background: #1c2534; }',
        '.lazii-msgs { flex: 1; overflow-y: auto; padding: 12px; display: flex; flex-direction: column; gap: 10px; scrollbar-width: thin; }',
        '.lazii-msg { max-width: 85%; padding: 9px 12px; border-radius: 12px; font-size: 13px; line-height: 1.45; white-space: pre-wrap; word-break: break-word; animation: lazii-pop .2s ease; }',
        '@keyframes lazii-pop { from { transform: scale(.96); opacity: 0; } to { transform: scale(1); opacity: 1; } }',
        '.lazii-msg.bot { background: #1c2534; border: 1px solid #2b3648; border-bottom-left-radius: 4px; align-self: flex-start; }',
        '.lazii-msg.me { background: #2b4a6f; border-bottom-right-radius: 4px; align-self: flex-end; }',
        '.lazii-chip { display: inline-block; font-size: 11px; background: #17301f; color: #7fd6a2; border: 1px solid #245c39; border-radius: 8px; padding: 3px 8px; margin: 4px 4px 0 0; animation: lazii-pop .25s ease; }',
        '.lazii-chip.evt { background: #16283e; color: #8fb8e8; border-color: #2b4a6f; }',
        '.lazii-chip.bad { background: #331719; color: #f08a8a; border-color: #6b2b2e; }',
        '.lazii-typing { display: inline-flex; gap: 4px; padding: 4px 2px; }',
        '.lazii-typing i { width: 6px; height: 6px; border-radius: 50%; background: #8fa0b8; animation: lazii-dot 1s infinite; }',
        '.lazii-typing i:nth-child(2) { animation-delay: .15s; } .lazii-typing i:nth-child(3) { animation-delay: .3s; }',
        '@keyframes lazii-dot { 0%,100% { transform: translateY(0); opacity: .4; } 50% { transform: translateY(-4px); opacity: 1; } }',
        '.lazii-input { display: flex; gap: 8px; padding: 10px; border-top: 1px solid #2b3648; background: #0f1520; }',
        '.lazii-input input { flex: 1; background: #1c2534; border: 1px solid #2b3648; color: #e8e2d6; border-radius: 10px; padding: 10px 12px; font-size: 13px; outline: none; }',
        '.lazii-input input:focus { border-color: #4f7ec2; box-shadow: 0 0 0 3px rgba(79,126,194,.2); }',
        '.lazii-input button { background: #4f7ec2; color: #fff; border: none; border-radius: 10px; padding: 0 16px; font-weight: 700; cursor: pointer; }',
        '.lazii-input button:hover { background: #5f8ed2; }',
        '.lazii-input button:disabled { background: #35465e; cursor: wait; }',

        /* sparkle burst when Lazii applies a change */
        '.lazii-spark { position: absolute; width: 6px; height: 6px; border-radius: 50%; background: #ffd76a; pointer-events: none; animation: lazii-spark .7s ease-out forwards; }',
        '@keyframes lazii-spark { from { transform: translate(0,0) scale(1); opacity: 1; } to { transform: translate(var(--dx), var(--dy)) scale(0); opacity: 0; } }'
    ].join('\n');

    /* The mascot himself: Lazii-Bot. Round, well-fed, a bit scruffy. */
    function mascotSVG(cls) {
        return '' +
        '<svg class="lazii-svg ' + (cls || '') + '" viewBox="0 0 120 120" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">' +
            '<defs>' +
                '<radialGradient id="laziiBody" cx="35%" cy="30%" r="80%">' +
                    '<stop offset="0%" stop-color="#7d9c8b"/><stop offset="70%" stop-color="#62806f"/><stop offset="100%" stop-color="#4d675a"/>' +
                '</radialGradient>' +
                '<radialGradient id="laziiBelly" cx="40%" cy="35%" r="75%">' +
                    '<stop offset="0%" stop-color="#a8c2b0"/><stop offset="100%" stop-color="#8aa693"/>' +
                '</radialGradient>' +
            '</defs>' +
            /* droopy antenna */
            '<path d="M60 22 C 58 12, 50 10, 42 14" stroke="#4d675a" stroke-width="3.5" fill="none" stroke-linecap="round"/>' +
            '<circle cx="41" cy="14.5" r="4.5" fill="#e0b84f"/>' +
            /* dented head */
            '<path d="M38 24 Q 60 8 82 24 Q 88 30 86 40 L 34 40 Q 32 30 38 24 Z" fill="url(#laziiBody)" stroke="#41584c" stroke-width="2"/>' +
            '<path d="M72 15 l 6 5" stroke="#41584c" stroke-width="2" stroke-linecap="round"/>' +
            /* sleepy eyes */
            '<g class="lazii-eye">' +
                '<ellipse cx="49" cy="33" rx="6.5" ry="5" fill="#16202b"/>' +
                '<circle cx="51" cy="31.5" r="1.4" fill="#dfe9ef"/>' +
            '</g>' +
            '<g class="lazii-eye">' +
                '<ellipse cx="72" cy="33" rx="6.5" ry="5" fill="#16202b"/>' +
                '<circle cx="74" cy="31.5" r="1.4" fill="#dfe9ef"/>' +
            '</g>' +
            '<path d="M53 43 Q 60 46.5 68 43" stroke="#2e3f36" stroke-width="2" fill="none" stroke-linecap="round"/>' +
            /* chubby body */
            '<ellipse cx="60" cy="76" rx="38" ry="34" fill="url(#laziiBody)" stroke="#41584c" stroke-width="2"/>' +
            /* belly panel */
            '<ellipse cx="60" cy="82" rx="24" ry="21" fill="url(#laziiBelly)" stroke="#5b7565" stroke-width="1.5"/>' +
            '<path d="M50 76 q 4 -3 8 0 q 4 3 8 0" stroke="#5b7565" stroke-width="1.6" fill="none" stroke-linecap="round"/>' +
            '<circle cx="60" cy="84" r="3.4" fill="#5b7565"/>' +
            /* grime and rust stains */
            '<ellipse cx="41" cy="62" rx="6" ry="3.6" fill="#6d5138" opacity=".5"/>' +
            '<ellipse cx="82" cy="88" rx="5" ry="3" fill="#6d5138" opacity=".45"/>' +
            '<ellipse cx="55" cy="99" rx="7" ry="2.6" fill="#54432f" opacity=".35"/>' +
            '<path d="M36 92 q 3 2 6 1" stroke="#54432f" stroke-width="1.4" opacity=".5" fill="none"/>' +
            /* stubby arms - left scratching the belly */
            '<rect x="14" y="66" width="14" height="10" rx="5" fill="#5b7565" stroke="#41584c" stroke-width="1.5" transform="rotate(18 21 71)"/>' +
            '<rect x="92" y="68" width="14" height="10" rx="5" fill="#5b7565" stroke="#41584c" stroke-width="1.5" transform="rotate(-14 99 73)"/>' +
            /* stubby feet */
            '<rect x="42" y="106" width="15" height="9" rx="4.5" fill="#41584c"/>' +
            '<rect x="64" y="106" width="15" height="9" rx="4.5" fill="#41584c"/>' +
            /* floating zzz when idle */
            '<g fill="#cfd8cf" font-family="monospace" font-weight="bold" font-size="10">' +
                '<text class="lazii-zzz" x="88" y="30">z</text>' +
                '<text class="lazii-zzz z2" x="94" y="24">z</text>' +
                '<text class="lazii-zzz z3" x="99" y="18">Z</text>' +
            '</g>' +
        '</svg>';
    }

    var CANNED = [
        "*pats couch* Mphf... hey. Turn me on properly first: flip 'Use AI' in the Account tab and give me a key (or point me at Ollama). Then I can change settings for you while you lounge.",
        "Zzz... oh, hey. I can flip your search terms, location, filters, headless mode, swap resumes - all from right here. Feed me an AI key in the Account tab and watch me work.",
        "*stretches* The couch is comfy but my brain is unplugged. Account tab -> Use AI -> ON. Then talk to me."
    ];

    var root, panel, msgs, input, sendBtn, bubble, thinkTimer = null;

    function el(tag, attrs, text) {
        var n = document.createElement(tag);
        if (attrs) for (var k in attrs) n.setAttribute(k, attrs[k]);
        if (text !== undefined) n.textContent = text;
        return n;
    }

    function addMsg(kind, text) {
        var m = el('div', { 'class': 'lazii-msg ' + kind });
        m.textContent = text;
        msgs.appendChild(m);
        msgs.scrollTop = msgs.scrollHeight;
        return m;
    }

    function addChips(applied, errors, events) {
        var last = msgs.lastChild;
        (events || []).forEach(function (e) {
            last.appendChild(el('span', { 'class': 'lazii-chip evt' }, e));
        });
        (applied || []).forEach(function (a) {
            last.appendChild(el('span', { 'class': 'lazii-chip' },
                'set ' + a.section + '.' + a.key + ' = ' + String(a.value)));
        });
        (errors || []).forEach(function (e) {
            last.appendChild(el('span', { 'class': 'lazii-chip bad' }, e));
        });
        msgs.scrollTop = msgs.scrollHeight;
    }

    function sparkle(node) {
        var r = node.getBoundingClientRect();
        for (var i = 0; i < 10; i++) {
            var s = el('span', { 'class': 'lazii-spark' });
            s.style.left = (r.left + r.width / 2) + 'px';
            s.style.top = (r.top + r.height / 2) + 'px';
            s.style.setProperty('--dx', (Math.random() * 90 - 45) + 'px');
            s.style.setProperty('--dy', (-30 - Math.random() * 60) + 'px');
            document.body.appendChild(s);
            (function (elx) { setTimeout(function () { elx.remove(); }, 750); })(s);
        }
    }

    function setThinking(on) {
        bubble.classList.toggle('lazii-think', on);
        if (on) {
            thinkTimer = addMsg('bot', '');
            var t = el('span', { 'class': 'lazii-typing' });
            t.appendChild(el('i')); t.appendChild(el('i')); t.appendChild(el('i'));
            thinkTimer.appendChild(t);
        } else if (thinkTimer) {
            thinkTimer.remove(); thinkTimer = null;
        }
    }

    function send() {
        var text = input.value.trim();
        if (!text) return;
        input.value = '';
        addMsg('me', text);
        setThinking(true);
        bubble.classList.remove('lazii-wobble'); void bubble.offsetWidth;
        bubble.classList.add('lazii-wobble');
        fetch('/api/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message: text })
        }).then(function (r) { return r.json(); }).then(function (data) {
            setThinking(false);
            if (data && data.say) {
                addMsg('bot', data.say);
                if ((data.applied && data.applied.length) || (data.errors && data.errors.length) || (data.events && data.events.length)) {
                    addChips(data.applied, data.errors, data.events);
                    if (data.applied && data.applied.length) sparkle(bubble);
                    try { window.dispatchEvent(new CustomEvent('lazii:config-changed', { detail: data })); } catch (e) {}
                }
            } else {
                addMsg('bot', data && data.error ? 'Ugh, the server said: ' + data.error : '...nothing came back. Try again?');
            }
        }).catch(function (err) {
            setThinking(false);
            addMsg('bot', 'Could not reach my brain: ' + err + ' (is the panel still running?)');
        });
    }

    function build() {
        var style = document.createElement('style');
        style.textContent = CSS;
        document.head.appendChild(style);

        root = el('div', { id: 'lazii-root', 'class': 'lazii-root' });

        panel = el('div', { 'class': 'lazii-panel' });
        var head = el('div', { 'class': 'lazii-head' });
        var mini = el('span', { 'class': 'lazii-mini' });
        mini.innerHTML = mascotSVG('');
        head.appendChild(mini);
        var tw = el('div');
        tw.appendChild(el('div', { 'class': 'lazii-title' }, 'Lazii-Bot'));
        tw.appendChild(el('div', { 'class': 'lazii-sub' }, 'your couch-potato job hunter'));
        head.appendChild(tw);
        var close = el('button', { type: 'button', 'aria-label': 'Close chat' }, 'x');
        close.addEventListener('click', function () { root.classList.remove('open'); });
        head.appendChild(close);
        panel.appendChild(head);

        msgs = el('div', { 'class': 'lazii-msgs' });
        panel.appendChild(msgs);

        var inputRow = el('div', { 'class': 'lazii-input' });
        input = el('input', { type: 'text', placeholder: 'Tell Lazii-Bot what to change...' });
        input.addEventListener('keydown', function (e) { if (e.key === 'Enter') send(); });
        sendBtn = el('button', { type: 'button' }, 'Send');
        sendBtn.addEventListener('click', send);
        inputRow.appendChild(input);
        inputRow.appendChild(sendBtn);
        panel.appendChild(inputRow);

        bubble = el('button', { type: 'button', 'class': 'lazii-bubble', 'aria-label': 'Open Lazii-Bot chat' });
        bubble.innerHTML = mascotSVG('') + '<span class="lazii-tip">talk to Lazii-Bot</span>';
        bubble.addEventListener('click', function () {
            root.classList.toggle('open');
            if (root.classList.contains('open')) input.focus();
        });

        root.appendChild(panel);
        root.appendChild(bubble);
        document.body.appendChild(root);

        addMsg('bot', "Welcome 2 The Couch. I'm Lazii-Bot - I hunt jobs while you stay horizontal. Ask me to change settings, switch your resume, or start a run.");
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', build);
    } else {
        build();
    }
})();
