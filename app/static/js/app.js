/*
 * reference_app.js — chování stránky pro webové aplikace
 * -----------------------------------------------------------------------------
 * Zkopíruj do app/static/js/app.js a načti v base.html:
 *     <script src="/static/js/app.js?v={{ app_version }}" defer></script>
 *
 * Všechno je řízené atributy v HTML, žádná inicializace v šablonách:
 *   data-confirm          potvrzení akce modalem místo confirm()
 *   data-keep-scroll      po odeslání formuláře zůstane pozice na stránce
 *   data-remember-open    <details> si pamatuje, jestli bylo rozbalené
 *   data-lightbox         fotka se otevře v překryvu, ne na nové kartě
 *   data-stepper          pole s tlačítky − / +
 *   data-set-value        rychlá předvolba hodnoty
 *   data-file-list        výpis vybraných souborů u dropzóny
 *   data-add-block        opakovatelný blok formuláře (šablona <template>)
 *   data-suggest-url      napovídání z číselníku v textovém poli
 *
 * Přidáváš-li chování, drž stejný postup: jeden atribut, jedna funkce,
 * obsluha delegovaná na document (funguje i pro obsah doplněný přes HTMX).
 */

// ---------------------------------------------------------------------------
// Toast
// ---------------------------------------------------------------------------

function showNotification(message, type) {
    type = type || 'info';
    var container = document.getElementById('notification-toast');
    if (!container) return;
    var el = document.createElement('div');
    el.className = 'toast toast--' + type;
    el.textContent = message;
    container.appendChild(el);
    setTimeout(function () {
        el.classList.add('toast--hide');
        setTimeout(function () { el.remove(); }, 300);
    }, 3500);
}

// ---------------------------------------------------------------------------
// Potvrzovací modal
// ---------------------------------------------------------------------------

var _confirmCb = null;

function confirmAction(title, message, okLabel, cb, danger) {
    document.getElementById('confirm-title').textContent = title;
    document.getElementById('confirm-message').textContent = message;
    var ok = document.getElementById('confirm-ok');
    ok.textContent = okLabel || 'Potvrdit';
    ok.className = 'btn ' + (danger ? 'btn-danger' : 'btn-primary');
    document.getElementById('confirm-overlay').style.display = 'flex';
    _confirmCb = cb;
    ok.onclick = function () {
        var fn = _confirmCb;
        closeConfirm();
        if (fn) fn();
    };
    ok.focus();
}

function closeConfirm() {
    document.getElementById('confirm-overlay').style.display = 'none';
    _confirmCb = null;
}

// ---------------------------------------------------------------------------
// Lightbox (galerie s listováním)
// ---------------------------------------------------------------------------

var lightboxItems = [];
var lightboxIndex = -1;

function lightboxFullUrl(href) {
    if (!href) return '';
    // náhled → plná velikost
    return href.replace(/([?&])thumb=1(&)?/, function (_, a, b) {
        return b ? a : '';
    }).replace(/\?$/, '');
}

function collectLightboxItems() {
    var list = [];
    var seen = {};
    document.querySelectorAll('a[data-lightbox], [data-lightbox-src]').forEach(function (el) {
        var src = el.getAttribute('data-lightbox-src') || lightboxFullUrl(el.getAttribute('href'));
        if (!src || seen[src]) return;
        seen[src] = true;
        var img = el.querySelector('img');
        list.push({ src: src, alt: (img && img.alt) || el.getAttribute('aria-label') || '' });
    });
    return list;
}

function renderLightbox() {
    var img = document.getElementById('lightbox-img');
    var item = lightboxItems[lightboxIndex];
    if (!img || !item) return;
    img.src = item.src;
    img.alt = item.alt || '';
    var many = lightboxItems.length > 1;
    ['lightbox-prev', 'lightbox-next'].forEach(function (id) {
        var btn = document.getElementById(id);
        if (btn) btn.hidden = !many;
    });
    var counter = document.getElementById('lightbox-counter');
    if (counter) {
        counter.hidden = !many;
        counter.textContent = (lightboxIndex + 1) + ' / ' + lightboxItems.length;
    }
}

function stepLightbox(delta) {
    if (!lightboxItems.length) return;
    lightboxIndex = (lightboxIndex + delta + lightboxItems.length) % lightboxItems.length;
    renderLightbox();
}

function openLightbox(src, alt) {
    var box = document.getElementById('lightbox');
    if (!box || !src) return;
    lightboxItems = collectLightboxItems();
    lightboxIndex = lightboxItems.findIndex(function (i) { return i.src === src; });
    if (lightboxIndex === -1) {
        lightboxItems = [{ src: src, alt: alt || '' }];
        lightboxIndex = 0;
    }
    box.hidden = false;
    document.body.classList.add('lightbox-open');
    renderLightbox();
    var closeBtn = document.getElementById('lightbox-close');
    if (closeBtn) closeBtn.focus();
}

function closeLightbox() {
    var box = document.getElementById('lightbox');
    var img = document.getElementById('lightbox-img');
    if (!box) return;
    box.hidden = true;
    document.body.classList.remove('lightbox-open');
    lightboxItems = [];
    lightboxIndex = -1;
    if (img) {
        img.removeAttribute('src');
        img.alt = '';
    }
}

// ---------------------------------------------------------------------------
// Motiv a šířka stránky (přepínače v zápatí)
// ---------------------------------------------------------------------------

function setTheme(mode) {
    var root = document.documentElement;
    if (mode === 'light' || mode === 'dark') {
        root.setAttribute('data-theme', mode);
        try { localStorage.setItem('theme', mode); } catch (e) {}
    } else {
        mode = 'auto';
        root.removeAttribute('data-theme');
        try { localStorage.removeItem('theme'); } catch (e) {}
    }
    document.querySelectorAll('[data-theme-option]').forEach(function (btn) {
        var active = btn.dataset.themeOption === mode;
        btn.classList.toggle('is-active', active);
        btn.setAttribute('aria-pressed', active ? 'true' : 'false');
    });
    // Barva systémové lišty prohlížeče podle právě platného pozadí.
    // Čte se až po přepnutí motivu, takže stačí jedna hodnota.
    var bg = getComputedStyle(document.documentElement).getPropertyValue('--color-bg').trim();
    document.querySelectorAll('meta[name="theme-color"]').forEach(function (m) { m.remove(); });
    var meta = document.createElement('meta');
    meta.name = 'theme-color';
    meta.content = bg;
    document.head.appendChild(meta);
}

function setWideLayout(on) {
    document.body.classList.toggle('layout-wide', !!on);
    try {
        if (on) localStorage.setItem('layout-wide', '1');
        else localStorage.removeItem('layout-wide');
    } catch (e) {}
    var btn = document.getElementById('layout-wide-toggle');
    if (btn) {
        btn.classList.toggle('is-active', !!on);
        btn.setAttribute('aria-pressed', on ? 'true' : 'false');
    }
}

// ---------------------------------------------------------------------------
// Obsluha atributů
// ---------------------------------------------------------------------------

document.addEventListener('DOMContentLoaded', function () {

    // --- potvrzení akce: <form data-confirm="…"> -----------------------------
    document.addEventListener('submit', function (e) {
        var form = e.target;
        if (!form.hasAttribute || !form.hasAttribute('data-confirm') || form.dataset.confirmed) return;
        e.preventDefault();
        var submitter = e.submitter;
        confirmAction(
            form.dataset.confirmTitle || 'Opravdu?',
            form.dataset.confirm,
            form.dataset.confirmOk || 'Potvrdit',
            function () {
                form.dataset.confirmed = '1';
                if (form.requestSubmit) form.requestSubmit(submitter || undefined);
                else form.submit();
            },
            form.hasAttribute('data-confirm-danger')
        );
    }, true);

    var overlay = document.getElementById('confirm-overlay');
    if (overlay) {
        overlay.addEventListener('click', function (e) {
            if (e.target === overlay) closeConfirm();
        });
    }

    // --- Escape zavírá vše otevřené -----------------------------------------
    document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape') {
            closeLightbox();
            closeConfirm();
            document.body.classList.remove('mobile-nav-open');
            document.querySelectorAll('details.dropdown[open]').forEach(function (d) {
                d.removeAttribute('open');
            });
            return;
        }
        if (!document.getElementById('lightbox') || document.getElementById('lightbox').hidden) return;
        if (e.key === 'ArrowRight') stepLightbox(1);
        if (e.key === 'ArrowLeft') stepLightbox(-1);
    });

    // --- lightbox ------------------------------------------------------------
    document.addEventListener('click', function (e) {
        // Cmd/Ctrl/Shift+klik nechat prohlížeči (otevření na nové kartě)
        if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || e.button !== 0) return;
        var link = e.target.closest && e.target.closest('a[data-lightbox]');
        if (link) {
            e.preventDefault();
            var full = link.getAttribute('data-lightbox-src') || lightboxFullUrl(link.getAttribute('href'));
            var thumb = link.querySelector('img');
            openLightbox(full, (thumb && thumb.alt) || link.getAttribute('aria-label') || '');
            return;
        }
        var trigger = e.target.closest && e.target.closest('[data-lightbox-src]');
        if (trigger && !trigger.closest('a[data-lightbox]')) {
            e.preventDefault();
            openLightbox(trigger.getAttribute('data-lightbox-src'), trigger.getAttribute('alt') || '');
        }
    });

    var lightbox = document.getElementById('lightbox');
    if (lightbox) {
        lightbox.addEventListener('click', function (e) {
            if (e.target.closest('#lightbox-prev')) { stepLightbox(-1); return; }
            if (e.target.closest('#lightbox-next')) { stepLightbox(1); return; }
            if (e.target === lightbox || e.target.closest('#lightbox-close')) closeLightbox();
        });

        var touchX = null;
        lightbox.addEventListener('touchstart', function (e) {
            touchX = e.changedTouches[0].clientX;
        }, { passive: true });
        lightbox.addEventListener('touchend', function (e) {
            if (touchX === null) return;
            var dx = e.changedTouches[0].clientX - touchX;
            touchX = null;
            if (Math.abs(dx) > 60) stepLightbox(dx < 0 ? 1 : -1);
        }, { passive: true });
    }

    // --- rozbalovací menu: zavřít při kliknutí mimo --------------------------
    document.addEventListener('click', function (e) {
        document.querySelectorAll('details.dropdown[open]').forEach(function (d) {
            if (!d.contains(e.target)) d.removeAttribute('open');
        });
    });

    // --- zachování pozice: <form data-keep-scroll> ---------------------------
    var scrollKey = 'scroll:' + location.pathname;
    try {
        var saved = sessionStorage.getItem(scrollKey);
        if (saved !== null) {
            sessionStorage.removeItem(scrollKey);
            window.scrollTo(0, parseInt(saved, 10) || 0);
        }
    } catch (err) {}
    document.addEventListener('submit', function (e) {
        if (e.target.closest && e.target.closest('[data-keep-scroll]') && !e.defaultPrevented) {
            try { sessionStorage.setItem(scrollKey, String(window.scrollY)); } catch (err) {}
        }
    });

    // --- rozbalené sekce: <details id="…" data-remember-open> ---------------
    document.querySelectorAll('details[data-remember-open][id]').forEach(function (el) {
        var key = 'open:' + location.pathname + ':' + el.id;
        var stored;
        try { stored = sessionStorage.getItem(key); } catch (e) {}
        if (stored === '1') el.open = true;
        else if (stored === '0') el.open = false;
        el.addEventListener('toggle', function () {
            try { sessionStorage.setItem(key, el.open ? '1' : '0'); } catch (e) {}
        });
    });

    // --- stepper a předvolby -------------------------------------------------
    document.querySelectorAll('[data-stepper]').forEach(function (wrap) {
        var input = wrap.querySelector('input');
        wrap.querySelectorAll('[data-step]').forEach(function (btn) {
            btn.addEventListener('click', function () {
                var step = parseFloat(btn.dataset.step);
                var min = parseFloat(input.min);
                if (isNaN(min)) min = 0;
                var val = Math.round(((parseFloat(input.value) || 0) + step) * 100) / 100;
                input.value = Math.max(min, val);
                input.dispatchEvent(new Event('change', { bubbles: true }));
            });
        });
    });

    document.querySelectorAll('[data-set-value]').forEach(function (btn) {
        btn.addEventListener('click', function () {
            var target = document.getElementById(btn.dataset.target);
            if (!target) return;
            target.value = btn.dataset.setValue;
            target.dispatchEvent(new Event('change', { bubbles: true }));
        });
    });

    document.querySelectorAll('[data-preset-group]').forEach(function (group) {
        var target = document.getElementById(group.dataset.presetGroup);
        if (!target) return;
        function sync() {
            group.querySelectorAll('[data-set-value]').forEach(function (b) {
                b.classList.toggle('chip--active', parseFloat(b.dataset.setValue) === parseFloat(target.value));
            });
        }
        target.addEventListener('change', sync);
        target.addEventListener('input', sync);
        sync();
    });

    // --- výpis vybraných souborů u dropzóny ----------------------------------
    document.querySelectorAll('.file-drop[data-file-list]').forEach(function (drop) {
        var input = drop.querySelector('input[type="file"]');
        var list = document.getElementById(drop.dataset.fileList);
        if (!input || !list) return;
        ['dragenter', 'dragover'].forEach(function (evt) {
            drop.addEventListener(evt, function () { drop.classList.add('is-dragover'); });
        });
        ['dragleave', 'drop'].forEach(function (evt) {
            drop.addEventListener(evt, function () { drop.classList.remove('is-dragover'); });
        });
        input.addEventListener('change', function () {
            list.innerHTML = '';
            Array.prototype.forEach.call(input.files, function (f) {
                var li = document.createElement('li');
                li.textContent = f.name + ' (' + Math.max(1, Math.round(f.size / 1024)) + ' kB)';
                list.appendChild(li);
            });
        });
    });

    // --- opakovatelné bloky formuláře ---------------------------------------
    // <div id="bloky" class="editor-list">…</div>
    // <button data-add-block="bloky" data-block-template="blok-sablona">
    // <template id="blok-sablona"><fieldset class="editor-block">…</fieldset></template>
    document.querySelectorAll('[data-add-block]').forEach(function (btn) {
        btn.addEventListener('click', function () {
            var list = document.getElementById(btn.dataset.addBlock);
            var tpl = document.getElementById(btn.dataset.blockTemplate);
            if (!list || !tpl) return;
            list.appendChild(tpl.content.cloneNode(true));
            var added = list.lastElementChild;
            var field = added && added.querySelector('input, textarea');
            if (field) field.focus();
        });
    });

    document.addEventListener('click', function (e) {
        var btn = e.target.closest && e.target.closest('[data-remove-block]');
        if (!btn) return;
        var block = btn.closest('.editor-block');
        if (!block) return;
        var list = block.parentElement;
        var text = block.querySelector('textarea, input[type="text"]');
        var drop = function () {
            block.remove();
            if (list && !list.children.length) {
                var addBtn = document.querySelector('[data-add-block="' + list.id + '"]');
                if (addBtn) addBtn.click();
            }
        };
        if (text && text.value.trim()) {
            confirmAction('Odebrat blok?', 'Vypsaný obsah se po uložení ztratí.', 'Odebrat', drop, true);
        } else {
            drop();
        }
    });

    // --- přepínače v zápatí --------------------------------------------------
    if (document.querySelector('[data-theme-option]')) {
        var stored = 'auto';
        try { stored = localStorage.getItem('theme') || 'auto'; } catch (e) {}
        setTheme(stored);
        document.querySelectorAll('[data-theme-option]').forEach(function (btn) {
            btn.addEventListener('click', function () { setTheme(btn.dataset.themeOption); });
        });
    }

    var wideBtn = document.getElementById('layout-wide-toggle');
    if (wideBtn) {
        setWideLayout(document.body.classList.contains('layout-wide'));
        wideBtn.addEventListener('click', function () {
            setWideLayout(!document.body.classList.contains('layout-wide'));
        });
    }

    // --- zvýraznění vybrané položky v master–detailu -------------------------
    document.addEventListener('click', function (e) {
        var item = e.target.closest && e.target.closest('.split-item');
        if (!item) return;
        var list = item.closest('.split-items');
        if (!list) return;
        list.querySelectorAll('.split-item.is-selected').forEach(function (el) {
            el.classList.remove('is-selected');
        });
        item.classList.add('is-selected');
        var layout = item.closest('.split-layout');
        if (layout) layout.classList.add('has-selection');
    });
});

// ---------------------------------------------------------------------------
// Napovídání v textovém poli
// <textarea data-suggest-url="/ciselnik/suggest"> — server dostane ?line=<řádek>
// a vrací {"prefix": "2 kg ", "items": [{"name": "Mouka"}]}
// ---------------------------------------------------------------------------

(function () {
    var box = null;
    var boxArea = null;
    var items = [];
    var active = -1;
    var timer = null;
    var lastPrefix = '';

    function currentLine(area) {
        var pos = area.selectionStart;
        var value = area.value;
        var start = value.lastIndexOf('\n', pos - 1) + 1;
        var end = value.indexOf('\n', pos);
        if (end === -1) end = value.length;
        return { start: start, end: end, text: value.slice(start, end), caretAtEnd: pos === end };
    }

    function closeBox() {
        if (box) box.remove();
        box = null;
        boxArea = null;
        items = [];
        active = -1;
    }

    function applySuggestion(name) {
        if (!boxArea) return;
        var area = boxArea;
        var line = currentLine(area);
        var replacement = (lastPrefix || '') + name;
        area.value = area.value.slice(0, line.start) + replacement + area.value.slice(line.end);
        var caret = line.start + replacement.length;
        area.focus();
        area.setSelectionRange(caret, caret);
        closeBox();
    }

    function highlight(index) {
        if (!box) return;
        var buttons = box.querySelectorAll('.suggest-item');
        if (!buttons.length) return;
        active = (index + buttons.length) % buttons.length;
        buttons.forEach(function (b, i) { b.classList.toggle('is-active', i === active); });
    }

    function showBox(area, data) {
        closeBox();
        if (!data.items || !data.items.length) return;
        lastPrefix = data.prefix || '';
        boxArea = area;
        items = data.items;

        box = document.createElement('div');
        box.className = 'suggest-box';
        box.setAttribute('role', 'listbox');
        data.items.forEach(function (it) {
            var b = document.createElement('button');
            b.type = 'button';
            b.className = 'suggest-item';
            b.textContent = it.name;
            b.addEventListener('mousedown', function (e) {
                e.preventDefault();
                applySuggestion(it.name);
            });
            box.appendChild(b);
        });

        var wrap = area.closest('.editor-block') || area.parentElement;
        wrap.appendChild(box);
        box.style.top = (area.offsetTop + area.offsetHeight + 2) + 'px';
        box.style.left = area.offsetLeft + 'px';
        box.style.width = area.offsetWidth + 'px';
    }

    function fetchSuggestions(area) {
        var line = currentLine(area);
        if (!line.caretAtEnd || line.text.trim().length < 2) {
            closeBox();
            return;
        }
        fetch(area.dataset.suggestUrl + '?line=' + encodeURIComponent(line.text))
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (document.activeElement !== area) return;
                showBox(area, data);
            })
            .catch(closeBox);
    }

    document.addEventListener('DOMContentLoaded', function () {
        document.addEventListener('input', function (e) {
            var area = e.target;
            if (!area.matches || !area.matches('[data-suggest-url]')) return;
            clearTimeout(timer);
            timer = setTimeout(function () { fetchSuggestions(area); }, 220);
        });

        document.addEventListener('keydown', function (e) {
            var area = e.target;
            if (!area.matches || !area.matches('[data-suggest-url]') || !box) return;
            if (e.key === 'ArrowDown') {
                e.preventDefault();
                highlight(active + 1);
            } else if (e.key === 'ArrowUp') {
                e.preventDefault();
                highlight(active - 1);
            } else if (e.key === 'Escape') {
                closeBox();
            } else if ((e.key === 'Enter' || e.key === 'Tab') && active >= 0) {
                // Enter bez vybrané položky nechat na nový řádek
                e.preventDefault();
                applySuggestion(items[active].name);
            } else if (e.key === 'Tab' && items.length) {
                e.preventDefault();
                applySuggestion(items[0].name);
            }
        });

        document.addEventListener('focusout', function (e) {
            if (e.target.matches && e.target.matches('[data-suggest-url]')) {
                setTimeout(closeBox, 120);
            }
        });
    });
})();

// ---------------------------------------------------------------------------
// Výběr složky z prohlížeče (Nastavení → pár):
//   data-pick-target="id pole" + data-pick-value="cesta" → vyplní pole
//   data-browser-close="id prohlížeče"                 → prohlížeč zavře
// ---------------------------------------------------------------------------

document.addEventListener('click', function (e) {
    if (!e.target.closest) return;
    var pick = e.target.closest('[data-pick-target]');
    if (pick) {
        var input = document.getElementById(pick.getAttribute('data-pick-target'));
        if (input) {
            input.value = pick.getAttribute('data-pick-value');
            input.dispatchEvent(new Event('change', { bubbles: true }));
        }
    }
    var close = e.target.closest('[data-browser-close]');
    if (close) {
        var box = document.getElementById(close.getAttribute('data-browser-close'));
        if (box) {
            box.innerHTML = '';
            box.className = '';
        }
    }
});

// ---------------------------------------------------------------------------
// Výběr řádků tabulky: kontejner [data-selection], řádky input[name="key"],
// „označit vše“ [data-check-all], počet [data-selected-count],
// tlačítka aktivní jen s výběrem [data-needs-selection].
// ---------------------------------------------------------------------------

function updateSelection(scope) {
    var boxes = scope.querySelectorAll('input[type="checkbox"][name="key"]');
    var count = 0;
    boxes.forEach(function (b) { if (b.checked) count++; });
    scope.querySelectorAll('[data-selected-count]').forEach(function (el) { el.textContent = '(' + count + ')'; });
    scope.querySelectorAll('[data-needs-selection]').forEach(function (el) { el.disabled = count === 0; });
    var all = scope.querySelector('[data-check-all]');
    if (all) {
        all.checked = count > 0 && count === boxes.length;
        all.indeterminate = count > 0 && count < boxes.length;
    }
}

document.addEventListener('change', function (e) {
    var target = e.target;
    if (!target.closest) return;
    var scope = target.closest('[data-selection]');
    if (!scope) return;
    if (target.hasAttribute('data-check-all')) {
        scope.querySelectorAll('input[type="checkbox"][name="key"]').forEach(function (b) { b.checked = target.checked; });
    }
    updateSelection(scope);
});

// ---------------------------------------------------------------------------
// Toast z odpovědi serveru: hlavička HX-Trigger {"notify": {"message": …, "type": …}}
// ---------------------------------------------------------------------------

document.addEventListener('notify', function (e) {
    var detail = e.detail || {};
    if (detail.message) showNotification(detail.message, detail.type || 'success');
});
