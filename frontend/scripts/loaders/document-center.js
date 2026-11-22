/* ============================================================================
   document-center.js — Centro de Documentos ERP CALEBSYS
   Módulo: Documentos · Consulta e impresión
   Compatible con CSP estricta (script-src 'self') y Regla Global MAYÚSCULAS
   ============================================================================ */
(function (global) {
  'use strict';

  var STORAGE_RETURN_KEY = 'calebsys_doc_center_return_state_v1';

  var state = {
    boot: null,
    items: [],
    pagination: { page: 1, page_size: 25, total_items: 0, total_pages: 1 },
    metrics: null,
    filters: {
      q: '',
      view_preset: 'all',
      category: '',
      doc_subtype: '',
      sucursal_id: 'ALL',
      emisor: '',
      doc_nature: '',
      currency: '',
      importe_min: '',
      importe_max: '',
      doc_status: '',
      fiscal_status: '',
      dispatch_status: '',
      date_from: '',
      date_to: '',
      sort_by: 'emitted_at',
      sort_dir: 'desc'
    },
    ui: {
      view_mode: 'list',
      density: 'comfortable',
      drawer_width: 430,
      overlay_mode: false,
      columns: ['folio', 'tercero', 'sucursal', 'emision', 'total', 'estado']
    },
    activeSavedViewId: '',
    selectedBatchKeys: new Set(),
    activeDocId: null,
    activeDocKey: null,
    activeExpediente: null,
    docHistoryStack: [],
    preview: {
      format: 'CARTA',
      representation: 'original',
      page: 1,
      totalPages: 1,
      zoom: 100
    },
    dispatchSession: {
      operationKey: '',
      operationId: null,
      targetEntries: []
    },
    listAbort: null,
    expAbort: null,
    previewAbort: null,
    thumbObserver: null,
    thumbUrls: {}
  };

  /* ── UTILIDADES DE AUTENTICACIÓN, ESCAPE Y FORMATO ── */
  function getToken() {
    return localStorage.getItem('calebsys_token') ||
           sessionStorage.getItem('auth_token') ||
           localStorage.getItem('auth_token') || '';
  }

  function authHeaders(extra) {
    var h = Object.assign({}, extra || {});
    var tok = getToken();
    if (tok) h['Authorization'] = 'Bearer ' + tok;
    return h;
  }

  async function dcFetch(url, opts) {
    var options = Object.assign({ credentials: 'include' }, opts || {});
    options.headers = authHeaders(options.headers || {});
    if (options.body && typeof options.body === 'string' && !options.headers['Content-Type']) {
      options.headers['Content-Type'] = 'application/json';
    }
    var res = await fetch(url, options);
    if (res.status === 401) {
      var err401 = new Error('Sesión vencida. Vuelve a iniciar sesión para continuar.');
      err401.status = 401;
      throw err401;
    }
    if (!res.ok) {
      var detail = 'Error HTTP ' + res.status;
      try {
        var errJson = await res.json();
        if (errJson && errJson.detail) detail = String(errJson.detail);
      } catch (_) {}
      var err = new Error(detail);
      err.status = res.status;
      throw err;
    }
    var ct = res.headers.get('content-type') || '';
    if (ct.indexOf('application/json') !== -1) {
      return await res.json();
    }
    return res;
  }

  function esc(val) {
    if (val === null || val === undefined) return '';
    return String(val)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function fmtMoney(val, currency) {
    if (val === null || val === undefined || isNaN(Number(val))) return '—';
    try {
      return new Intl.NumberFormat('es-MX', {
        style: 'currency',
        currency: currency || 'MXN',
        minimumFractionDigits: 2
      }).format(Number(val));
    } catch (_) {
      return '$' + Number(val).toFixed(2);
    }
  }

  function fmtShortDate(isoOrLocal) {
    if (!isoOrLocal) return '—';
    try {
      var d = new Date(isoOrLocal.replace(' ', 'T'));
      if (isNaN(d.getTime())) return String(isoOrLocal);
      return d.toLocaleDateString('es-MX', { day: '2-digit', month: 'short', year: 'numeric' });
    } catch (_) {
      return String(isoOrLocal);
    }
  }

  function statusBadgeClass(st) {
    var s = String(st || '').toUpperCase();
    if (['EMITIDA', 'EMITIDO', 'APLICADA', 'APLICADO', 'ENTREGADA', 'PAGADO', 'COMPLETADA', 'FIRMADO', 'RECIBIDA', 'RECIBIDO'].indexOf(s) !== -1) {
      return 'dc-st-ok';
    }
    if (['TIMBRADA', 'TIMBRADO', 'VIGENTE', 'REGISTRADO', 'ACTIVO', 'ACTIVA', 'ABIERTO'].indexOf(s) !== -1) {
      return 'dc-st-info';
    }
    if (['PENDIENTE', 'PARCIAL', 'CON_DIFERENCIA', 'EN_TRANSITO', 'PENDIENTE_ENTREGA', 'INCIERTO'].indexOf(s) !== -1) {
      return 'dc-st-warn';
    }
    if (['CANCELADA', 'CANCELADO', 'CANCELADA_SAT', 'CON_ERROR', 'RECHAZADO'].indexOf(s) !== -1) {
      return 'dc-st-err';
    }
    return 'dc-st-neutral';
  }

  function prettyStatus(st) {
    var s = String(st || 'EMITIDO').replace(/_/g, ' ').toLowerCase();
    return s.charAt(0).toUpperCase() + s.slice(1);
  }

  function renderAmountCell(item) {
    if (item.amount_state === 'NOT_APPLICABLE' || !item.amount_applicable) {
      return '<span title="Importe no aplicable para este tipo de movimiento" style="color:var(--dc-muted);font-weight:600;">—</span>';
    }
    if (item.amount_state === 'REDACTED') {
      return '<span class="dc-status-pill dc-st-neutral" title="Importe reservado según permisos de tu rol"><i class="fa-solid fa-lock" aria-hidden="true"></i> Reservado</span>';
    }
    if (item.amount_state === 'ZERO') {
      return '<span title="Documento con importe cero ($0.00)">' + esc(fmtMoney(0, item.currency)) + '</span>';
    }
    return esc(fmtMoney(item.total_amount, item.currency));
  }

  function announce(msg) {
    var el = document.getElementById('dc-live-status');
    if (el) el.textContent = msg;
  }

  function showToastMsg(msg, type) {
    if (typeof global.toast === 'function') {
      global.toast(msg, type || 'info');
      return;
    }
    announce(msg);
  }

  /* ── MANEJO DE MODALES NATIVOS <dialog> ── */
  function openDialog(id) {
    var dlg = document.getElementById(id);
    if (!dlg) return;
    if (typeof dlg.showModal === 'function' && !dlg.open) {
      dlg.returnValue = '';
      dlg.showModal();
    }
  }

  function closeDialog(id) {
    var dlg = document.getElementById(id);
    if (!dlg) return;
    if (dlg.open && typeof dlg.close === 'function') {
      dlg.close();
      dlg.returnValue = '';
    }
  }

  /* ── SINCRONIZACIÓN DE TEMA Y SUPERFICIE ── */
  function applyUiSurfaceAndPrefs() {
    var root = document.getElementById('dc-root');
    if (!root) return;

    root.setAttribute('data-density', state.ui.density || 'comfortable');
    root.style.setProperty('--dc-drawer-w', (state.ui.drawer_width || 430) + 'px');

    // En 1366x768 permitimos modo superpuesto o acoplado
    var narrowDesktop = window.innerWidth <= 1420;
    root.classList.toggle('exp-overlay-mode', narrowDesktop ? !!state.ui.overlay_mode : false);
    root.removeAttribute('data-dc-theme'); // Sigue 100% el tema global (claro u oscuro, nunca mixto)

    // Columnas visibles en thead y celdas
    var visCols = new Set(state.ui.columns || ['folio', 'tercero', 'sucursal', 'emision', 'total', 'estado']);
    visCols.add('folio');
    root.querySelectorAll('[data-col]').forEach(function (cell) {
      var c = cell.getAttribute('data-col');
      cell.style.display = visCols.has(c) ? '' : 'none';
    });

    var btnList = document.getElementById('dc-view-list');
    var btnGrid = document.getElementById('dc-view-grid');
    var tblReg = document.getElementById('dc-table-region');
    var grdReg = document.getElementById('dc-grid-view');
    var isGrid = state.ui.view_mode === 'grid';
    if (btnList) btnList.setAttribute('aria-pressed', isGrid ? 'false' : 'true');
    if (btnGrid) btnGrid.setAttribute('aria-pressed', isGrid ? 'true' : 'false');
    if (tblReg) tblReg.style.display = isGrid ? 'none' : '';
    if (grdReg) grdReg.hidden = !isGrid;
  }

  /* ── GUARDAR / RESTAURAR ESTADO AL IR AL MOVIMIENTO ORIGINAL ── */
  function saveReturnState() {
    var tblReg = document.getElementById('dc-table-region');
    var payload = {
      filters: state.filters,
      page: state.pagination.page,
      activeDocKey: state.activeDocKey,
      scrollTop: tblReg ? tblReg.scrollTop : 0,
      savedAt: Date.now()
    };
    try {
      sessionStorage.setItem(STORAGE_RETURN_KEY, JSON.stringify(payload));
    } catch (_) {}
  }

  function tryRestoreReturnState() {
    try {
      var raw = sessionStorage.getItem(STORAGE_RETURN_KEY);
      if (!raw) return null;
      sessionStorage.removeItem(STORAGE_RETURN_KEY);
      var parsed = JSON.parse(raw);
      if (parsed && parsed.filters) {
        state.filters = Object.assign(state.filters, parsed.filters);
        state.pagination.page = parsed.page || 1;
        return parsed;
      }
    } catch (_) {}
    return null;
  }

  /* ── RENDERIZADO DE PESTAÑAS DE CATEGORÍA, SUBTIPOS Y VISTAS ── */
  function renderLibraryAndCategories() {
    if (!state.boot) return;
    var lib = state.boot.library || {};
    var cats = lib.categories || [];

    // Barra horizontal de categorías
    var qCatsEl = document.getElementById('dc-quick-cats');
    if (qCatsEl) {
      var qHtml = '<button type="button" role="tab" class="dc-cat-tab" data-qcat="" aria-selected="' + (!state.filters.category ? 'true' : 'false') + '">Todos</button>';
      cats.forEach(function (cat) {
        var sel = state.filters.category === cat.id ? 'true' : 'false';
        qHtml += '<button type="button" role="tab" class="dc-cat-tab" data-qcat="' + esc(cat.id) + '" aria-selected="' + sel + '">' + esc(cat.label) + '</button>';
      });
      qCatsEl.innerHTML = qHtml;
    }

    // Selector de subtipo (agrupado por categoría cuando está en Todos)
    var qSubEl = document.getElementById('dc-quick-subtype');
    if (qSubEl) {
      var opts = '<option value="">Tipo de documento</option>';
      if (state.filters.category) {
        cats.forEach(function (cat) {
          if (state.filters.category !== cat.id) return;
          (cat.subtypes || []).forEach(function (st) {
            var selAttr = state.filters.doc_subtype === st.id ? ' selected' : '';
            opts += '<option value="' + esc(st.id) + '"' + selAttr + '>' + esc(st.label) + '</option>';
          });
        });
      } else {
        cats.forEach(function (cat) {
          var subItems = cat.subtypes || [];
          if (!subItems.length) return;
          opts += '<optgroup label="' + esc(cat.label) + '">';
          subItems.forEach(function (st) {
            var selAttr = state.filters.doc_subtype === st.id ? ' selected' : '';
            opts += '<option value="' + esc(st.id) + '"' + selAttr + '>' + esc(st.label) + '</option>';
          });
          opts += '</optgroup>';
        });
      }
      qSubEl.innerHTML = opts;
    }

    // Selector compacto de vistas rápidas (Todos / Recientes / Favoritos) y vistas guardadas
    var svSel = document.getElementById('dc-saved-view-select');
    var svDelBtn = document.getElementById('dc-btn-del-saved-view');
    var savedViews = (state.boot.preferences && state.boot.preferences.saved_views) || [];
    if (svSel) {
      var curVal = state.activeSavedViewId ? ('view:' + state.activeSavedViewId) : ('preset:' + (state.filters.view_preset || 'all'));
      var vOpts = '<option value="preset:all"' + (curVal === 'preset:all' ? ' selected' : '') + '>Vista: Todos</option>' +
        '<option value="preset:recents"' + (curVal === 'preset:recents' ? ' selected' : '') + '>Recientes (' + esc(lib.recents_count || 0) + ')</option>' +
        '<option value="preset:favorites"' + (curVal === 'preset:favorites' ? ' selected' : '') + '>Favoritos (' + esc(lib.favorites_count || 0) + ')</option>';
      if (savedViews.length) {
        vOpts += '<optgroup label="Vistas guardadas">';
        savedViews.forEach(function (v) {
          var vKey = 'view:' + v.id;
          vOpts += '<option value="' + esc(vKey) + '"' + (curVal === vKey ? ' selected' : '') + '>' + esc(v.name) + '</option>';
        });
        vOpts += '</optgroup>';
      }
      svSel.innerHTML = vOpts;
    }
    if (svDelBtn) {
      svDelBtn.hidden = !state.activeSavedViewId;
    }

    updateDynamicTitle();
  }

  function updateDynamicTitle() {
    var titleEl = document.getElementById('dc-main-title');
    if (!titleEl || !state.boot) return;
    var base = 'Centro de documentos';
    var cats = (state.boot.library && state.boot.library.categories) || [];

    if (state.filters.doc_subtype) {
      cats.forEach(function (c) {
        (c.subtypes || []).forEach(function (st) {
          if (st.id === state.filters.doc_subtype) {
            base = 'Centro de documentos · ' + st.label;
          }
        });
      });
    } else if (state.filters.category) {
      cats.forEach(function (c) {
        if (c.id === state.filters.category) {
          base = 'Centro de documentos · ' + c.label;
        }
      });
    } else if (state.filters.view_preset === 'favorites') {
      base = 'Centro de documentos · Favoritos';
    } else if (state.filters.view_preset === 'recents') {
      base = 'Centro de documentos · Recientes';
    }
    titleEl.textContent = base;
  }

  /* ── CHIPS DE FILTROS ACTIVOS REMOVIBLES ── */
  function renderActiveFilterChips() {
    var wrap = document.getElementById('dc-active-chips');
    if (!wrap) return;
    var chips = [];
    var f = state.filters;

    if (f.q) chips.push({ key: 'q', label: 'Búsqueda: ' + f.q });
    if (f.category) {
      var catObj = ((state.boot && state.boot.library && state.boot.library.categories) || []).find(function (c) { return c.id === f.category; });
      chips.push({ key: 'category', label: 'Categoría: ' + ((catObj && catObj.label) || f.category).toUpperCase() });
    }
    if (f.doc_subtype) chips.push({ key: 'doc_subtype', label: 'Tipo: ' + f.doc_subtype.replace(/_/g, ' ').toUpperCase() });
    if (f.doc_status) chips.push({ key: 'doc_status', label: 'Estado: ' + f.doc_status });
    if (f.fiscal_status) chips.push({ key: 'fiscal_status', label: 'Fiscal: ' + f.fiscal_status });
    if (f.dispatch_status) chips.push({ key: 'dispatch_status', label: 'Envío: ' + f.dispatch_status });
    if (f.emisor) chips.push({ key: 'emisor', label: 'Emisor: ' + f.emisor });
    if (f.doc_nature) chips.push({ key: 'doc_nature', label: 'Naturaleza: ' + f.doc_nature });
    if (f.currency) chips.push({ key: 'currency', label: 'Moneda: ' + f.currency });
    if (f.date_from) chips.push({ key: 'date_from', label: 'Desde: ' + f.date_from });
    if (f.date_to) chips.push({ key: 'date_to', label: 'Hasta: ' + f.date_to });
    if (f.importe_min !== '') chips.push({ key: 'importe_min', label: 'Mín: $' + f.importe_min });
    if (f.importe_max !== '') chips.push({ key: 'importe_max', label: 'Máx: $' + f.importe_max });

    if (!chips.length) {
      wrap.hidden = true;
      wrap.innerHTML = '';
      return;
    }

    wrap.hidden = false;
    var html = chips.map(function (c) {
      return '<span class="dc-active-chip">' + esc(c.label) +
        '<button type="button" data-remove-chip="' + esc(c.key) + '" aria-label="Quitar filtro ' + esc(c.label) + '">×</button>' +
        '</span>';
    }).join('');
    html += '<button type="button" class="dc-link-btn" id="dc-clear-all-filters" style="font-size:11.5px;">Limpiar filtros</button>';
    wrap.innerHTML = html;
  }

  /* ── CARGA DE LISTADO EN SERVIDOR CON CANCELACIÓN DE CARRERA (AbortController) ── */
  function buildListQueryParams(extraParams) {
    var p = new URLSearchParams();
    var f = state.filters;
    if (f.q) p.set('q', f.q);
    if (f.view_preset && f.view_preset !== 'all') p.set('view_preset', f.view_preset);
    if (f.category) p.set('category', f.category);
    if (f.doc_subtype) p.set('doc_subtype', f.doc_subtype);
    if (f.sucursal_id) p.set('sucursal_id', f.sucursal_id);
    if (f.emisor) p.set('emisor', f.emisor);
    if (f.doc_nature) p.set('doc_nature', f.doc_nature);
    if (f.currency) p.set('currency', f.currency);
    if (f.importe_min !== '' && f.importe_min !== null) p.set('importe_min', String(f.importe_min));
    if (f.importe_max !== '' && f.importe_max !== null) p.set('importe_max', String(f.importe_max));
    if (f.doc_status) p.set('doc_status', f.doc_status);
    if (f.fiscal_status) p.set('fiscal_status', f.fiscal_status);
    if (f.dispatch_status) p.set('dispatch_status', f.dispatch_status);
    if (f.date_from) p.set('date_from', f.date_from);
    if (f.date_to) p.set('date_to', f.date_to);
    p.set('sort_by', f.sort_by || 'emitted_at');
    p.set('sort_dir', f.sort_dir || 'desc');
    p.set('page', String(state.pagination.page || 1));
    p.set('page_size', String(state.pagination.page_size || 25));

    if (extraParams) {
      Object.keys(extraParams).forEach(function (k) {
        p.set(k, String(extraParams[k]));
      });
    }
    return p;
  }

  async function loadDocumentsList(opts) {
    var options = opts || {};
    if (state.listAbort) {
      state.listAbort.abort();
    }
    var ctrl = new AbortController();
    state.listAbort = ctrl;

    renderActiveFilterChips();
    var tbody = document.getElementById('dc-tbody');
    if (tbody && !options.silent) {
      tbody.innerHTML = '<tr><td colspan="8"><div class="dc-state-box"><i class="fa-solid fa-spinner fa-spin" aria-hidden="true"></i><strong>Consultando documentos...</strong></div></td></tr>';
    }

    try {
      var params = buildListQueryParams({ sync: options.sync === false ? 'false' : 'true' });
      var data = await dcFetch('/api/documents?' + params.toString(), { signal: ctrl.signal });
      if (state.listAbort !== ctrl) return;

      state.items = data.items || [];
      state.pagination = data.pagination || { page: 1, page_size: 25, total_items: 0, total_pages: 1 };
      state.metrics = data.metrics || null;

      renderMetricsAndConsolidado(data);
      renderTableAndThumbnails();
      renderPagination();
      applyUiSurfaceAndPrefs();

      var stamp = document.getElementById('dc-sync-stamp');
      if (stamp && state.metrics) {
        stamp.textContent = 'Actualizado · Zona ' + (state.metrics.branch_timezone || 'local');
      }

      if (options.restoreDocKey) {
        var found = state.items.find(function (x) { return x.doc_key === options.restoreDocKey; });
        if (found) {
          openDocumentExpediente(found.id, false);
        }
      }
      if (typeof options.restoreScrollTop === 'number') {
        var tblReg = document.getElementById('dc-table-region');
        if (tblReg) tblReg.scrollTop = options.restoreScrollTop;
      }
    } catch (err) {
      if (err && err.name === 'AbortError') return;
      renderErrorStateInTable(err);
    }
  }

  function renderErrorStateInTable(err) {
    var tbody = document.getElementById('dc-tbody');
    if (!tbody) return;
    var status = err && err.status;
    var ico = status === 401 ? 'fa-lock' : (status === 403 ? 'fa-ban' : 'fa-triangle-exclamation');
    var title = status === 401 ? 'Sesión vencida' : (status === 403 ? 'Sin permiso para esta consulta' : 'Error recuperable al consultar');
    var actionBtn = status === 401
      ? '<a href="/login" class="dc-btn dc-btn-primary" style="margin-top:8px;text-decoration:none;">Iniciar sesión nuevamente</a>'
      : '<button type="button" class="dc-btn dc-btn-primary" id="dc-btn-retry-list" style="margin-top:8px;"><i class="fa-solid fa-rotate-right"></i> Reintentar consulta</button>';

    tbody.innerHTML = '<tr><td colspan="8"><div class="dc-state-box">' +
      '<i class="fa-solid ' + ico + '" style="color:var(--dc-err-txt);" aria-hidden="true"></i>' +
      '<strong style="color:var(--dc-text);font-size:14px;">' + esc(title) + '</strong>' +
      '<span>' + esc(err ? err.message : 'No fue posible obtener los documentos.') + '</span>' +
      actionBtn +
      '</div></td></tr>';
  }

  function renderMetricsAndConsolidado(data) {
    var m = data.metrics || {};
    var elRes = document.getElementById('dc-num-results');
    var elTod = document.getElementById('dc-num-today');
    var elErrBtn = document.getElementById('dc-metric-errors');
    var elErrNum = document.getElementById('dc-num-errors');

    if (elRes) elRes.textContent = String(m.filtered_count || 0);
    if (elTod) elTod.textContent = String(m.emitted_today_count || 0);

    var errCnt = Number(m.dispatch_errors_count || 0);
    if (elErrBtn && elErrNum) {
      elErrNum.textContent = String(errCnt);
      elErrBtn.hidden = errCnt <= 0;
    }

    if (m.explanations) {
      var exF = document.getElementById('dc-exp-filtered');
      var exT = document.getElementById('dc-exp-today');
      var exE = document.getElementById('dc-exp-errors');
      if (exF) exF.textContent = m.explanations.filtered_count || '';
      if (exT) exT.textContent = m.explanations.emitted_today_count || '';
      if (exE) exE.textContent = m.explanations.dispatch_errors_count || '';
    }

    // Consolidado de Cortes Z exclusivo en pantalla para Admin General
    var czBanner = document.getElementById('dc-corte-consolidado-banner');
    var cz = data.corte_z_consolidado_screen;
    if (czBanner) {
      if (!cz) {
        czBanner.hidden = true;
        czBanner.innerHTML = '';
      } else {
        czBanner.hidden = false;
        var branchesHtml = (cz.by_branch || []).map(function (b) {
          return '<span class="dc-metric-chip"><strong>' + esc(b.sucursal_id) + ':</strong> ' +
            esc(b.cortes_count) + ' corte(s) · ' + esc(fmtMoney(b.total_declarado, 'MXN')) + '</span>';
        }).join(' ');
        czBanner.innerHTML =
          '<div style="display:flex;align-items:center;justify-content:space-between;gap:8px;flex-wrap:wrap;">' +
            '<div style="font-size:12.5px;font-weight:800;color:var(--dc-blue);">' +
              '<i class="fa-solid fa-eye" aria-hidden="true"></i> Consolidado de Cortes Z (Matriz y Sucursales) — Total: ' + esc(fmtMoney(cz.grand_total, 'MXN')) +
            '</div>' +
            '<span class="dc-status-pill dc-st-warn">Solo consulta en pantalla · No imprimible ni exportable</span>' +
          '</div>' +
          '<div style="display:flex;gap:6px;flex-wrap:wrap;">' + branchesHtml + '</div>' +
          '<div style="font-size:11px;color:var(--dc-muted);">' + esc(cz.policy_notice) + '</div>';
      }
    }
  }

  /* ── RENDERIZADO DE FILAS Y MINIATURAS BAJO DEMANDA ── */
  function renderTableAndThumbnails() {
    var tbody = document.getElementById('dc-tbody');
    var grid = document.getElementById('dc-grid-view');
    if (!tbody || !grid) return;

    var hasAnyFilter = !!(
      state.filters.q || state.filters.category || state.filters.doc_subtype ||
      state.filters.doc_status || state.filters.fiscal_status || state.filters.dispatch_status ||
      state.filters.date_from || state.filters.date_to || state.filters.emisor ||
      state.filters.view_preset !== 'all'
    );

    if (!state.items.length) {
      var emptyTitle = hasAnyFilter ? 'Sin coincidencias para los filtros actuales' : 'Aún no hay documentos emitidos en este alcance';
      var emptySub = hasAnyFilter
        ? 'Prueba ajustando el término de búsqueda, el rango de fechas o limpia los filtros activos.'
        : 'Los comprobantes de ventas, caja, compras, almacén, cartera y facturación aparecerán aquí conforme se emitan.';
      var clearBtn = hasAnyFilter
        ? '<button type="button" class="dc-btn" id="dc-empty-clear-btn" style="margin-top:8px;">Restablecer filtros</button>'
        : '';
      var emptyMarkup = '<div class="dc-state-box">' +
        '<i class="fa-regular fa-folder-open" aria-hidden="true"></i>' +
        '<strong style="color:var(--dc-text);font-size:14px;">' + esc(emptyTitle) + '</strong>' +
        '<span>' + esc(emptySub) + '</span>' + clearBtn + '</div>';

      tbody.innerHTML = '<tr><td colspan="8">' + emptyMarkup + '</td></tr>';
      grid.innerHTML = '<div style="grid-column:1/-1;">' + emptyMarkup + '</div>';
      updateBatchBar();
      return;
    }

    tbody.innerHTML = state.items.map(function (it) {
      var isAct = state.activeDocKey === it.doc_key;
      var isChk = state.selectedBatchKeys.has(it.doc_key);
      var stCls = statusBadgeClass(it.doc_status);
      var errDot = it.dispatch_status === 'CON_ERROR'
        ? '<span title="Último envío con error" style="color:var(--dc-err-txt);font-size:11px;"><i class="fa-solid fa-triangle-exclamation"></i></span>'
        : '';

      return '<tr class="dc-doc-row ' + (isAct ? 'active' : '') + '" tabindex="0" data-doc-id="' + esc(it.id) + '" data-doc-key="' + esc(it.doc_key) + '">' +
        '<td class="dc-col-check">' +
          '<input type="checkbox" class="dc-row-check" data-batch-key="' + esc(it.doc_key) + '"' + (isChk ? ' checked' : '') + ' aria-label="Seleccionar ' + esc(it.folio_visible) + ' para lote">' +
        '</td>' +
        '<td data-col="folio">' +
          '<div class="dc-doc-cell">' +
            '<span class="dc-doc-ico cat-' + esc(it.category) + '" aria-hidden="true"><i class="fa-solid ' + esc(it.icon) + '"></i></span>' +
            '<div>' +
              '<div class="dc-folio-main">' + esc(it.folio_visible) + ' ' + errDot + '</div>' +
              '<div class="dc-folio-sub">' + esc(it.subtype_label) + '</div>' +
            '</div>' +
          '</div>' +
        '</td>' +
        '<td data-col="tercero"><div class="dc-tercero-main" title="' + esc(it.tercero_nombre) + '">' + esc(it.tercero_nombre || '—') + '</div></td>' +
        '<td data-col="sucursal"><span style="font-size:12px;color:var(--dc-text-2);font-weight:600;">' + esc(it.sucursal_id || 'MATRIZ') + '</span></td>' +
        '<td data-col="emision" style="color:var(--dc-text-2);">' + esc(fmtShortDate(it.emitted_local || it.emitted_at)) + '</td>' +
        '<td data-col="total" class="dc-num-col">' + renderAmountCell(it) + '</td>' +
        '<td data-col="estado"><span class="dc-status-pill ' + stCls + '">' + esc(prettyStatus(it.doc_status)) + '</span></td>' +
        '<td>' +
          '<div class="dc-row-actions">' +
            '<button type="button" class="dc-icon-btn ' + (it.is_favorite ? 'fav-on' : '') + '" data-fav-id="' + esc(it.id) + '" title="Favorito" aria-label="Marcar favorito ' + esc(it.folio_visible) + '">' +
              '<i class="' + (it.is_favorite ? 'fa-solid' : 'fa-regular') + ' fa-star" aria-hidden="true"></i>' +
            '</button>' +
            '<button type="button" class="dc-icon-btn" data-quick-open="' + esc(it.id) + '" title="Ver vista previa y expediente" aria-label="Abrir expediente ' + esc(it.folio_visible) + '">' +
              '<i class="fa-regular fa-eye" aria-hidden="true"></i>' +
            '</button>' +
            '<button type="button" class="dc-icon-btn" data-quick-print="' + esc(it.id) + '" title="Imprimir" aria-label="Imprimir ' + esc(it.folio_visible) + '">' +
              '<i class="fa-solid fa-print" aria-hidden="true"></i>' +
            '</button>' +
          '</div>' +
        '</td>' +
      '</tr>';
    }).join('');

    // Tarjetas de Miniaturas (cargadas bajo demanda con IntersectionObserver)
    grid.innerHTML = state.items.map(function (it) {
      var isAct = state.activeDocKey === it.doc_key;
      var isChk = state.selectedBatchKeys.has(it.doc_key);
      var stCls = statusBadgeClass(it.doc_status);
      return '<article class="dc-thumb-card ' + (isAct ? 'active' : '') + '" tabindex="0" data-doc-id="' + esc(it.id) + '" data-doc-key="' + esc(it.doc_key) + '">' +
        '<div class="dc-thumb-img-wrap" data-lazy-thumb="' + esc(it.id) + '">' +
          '<div class="dc-thumb-chk-wrap">' +
            '<input type="checkbox" class="dc-row-check" data-batch-key="' + esc(it.doc_key) + '"' + (isChk ? ' checked' : '') + ' aria-label="Seleccionar ' + esc(it.folio_visible) + '">' +
          '</div>' +
          '<span style="font-size:11.5px;color:var(--dc-muted);"><i class="fa-regular fa-image"></i> Vista previa...</span>' +
        '</div>' +
        '<div class="dc-thumb-meta">' +
          '<div style="display:flex;justify-content:space-between;align-items:center;gap:4px;">' +
            '<strong style="font-size:12.5px;">' + esc(it.folio_visible) + '</strong>' +
            '<span class="dc-status-pill ' + stCls + '" style="font-size:10px;padding:2px 7px;">' + esc(prettyStatus(it.doc_status)) + '</span>' +
          '</div>' +
          '<div style="font-size:11.5px;color:var(--dc-muted);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">' + esc(it.tercero_nombre || it.subtype_label) + '</div>' +
          '<div style="display:flex;justify-content:space-between;font-size:11.5px;font-weight:700;margin-top:2px;">' +
            '<span style="color:var(--dc-muted);font-weight:500;">' + esc(fmtShortDate(it.emitted_local || it.emitted_at)) + '</span>' +
            '<span>' + renderAmountCell(it) + '</span>' +
          '</div>' +
        '</div>' +
      '</article>';
    }).join('');

    if (state.ui.view_mode === 'grid') {
      setupLazyThumbnailsObserver();
    }
    updateBatchBar();
  }

  function setupLazyThumbnailsObserver() {
    if (state.thumbObserver) {
      state.thumbObserver.disconnect();
    }
    var containers = document.querySelectorAll('[data-lazy-thumb]');
    if (!containers.length || typeof IntersectionObserver === 'undefined') return;

    state.thumbObserver = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (!entry.isIntersecting) return;
        var wrap = entry.target;
        var docId = wrap.getAttribute('data-lazy-thumb');
        state.thumbObserver.unobserve(wrap);
        if (!docId || wrap.dataset.loaded === '1') return;
        wrap.dataset.loaded = '1';

        fetch('/api/documents/item/' + encodeURIComponent(docId) + '/thumbnail', {
          credentials: 'include',
          headers: authHeaders()
        }).then(function (r) {
          if (!r.ok) throw new Error('thumb');
          return r.blob();
        }).then(function (blob) {
          var url = URL.createObjectURL(blob);
          state.thumbUrls[docId] = url;
          var chk = wrap.querySelector('.dc-thumb-chk-wrap');
          wrap.innerHTML = '';
          if (chk) wrap.appendChild(chk);
          var img = document.createElement('img');
          img.src = url;
          img.alt = 'Miniatura documental';
          wrap.appendChild(img);
        }).catch(function () {});
      });
    }, { root: document.getElementById('dc-grid-view'), rootMargin: '80px' });

    containers.forEach(function (c) { state.thumbObserver.observe(c); });
  }

  function renderPagination() {
    var p = state.pagination;
    var info = document.getElementById('dc-pagination-info');
    var ind = document.getElementById('dc-page-indicator');
    var prev = document.getElementById('dc-page-prev');
    var next = document.getElementById('dc-page-next');

    if (info) {
      info.textContent = p.total_items > 0
        ? (p.from_index + '–' + p.to_index + ' de ' + p.total_items)
        : '0 resultados';
    }
    if (ind) ind.textContent = 'Página ' + p.page + ' de ' + p.total_pages;
    if (prev) prev.disabled = p.page <= 1;
    if (next) next.disabled = p.page >= p.total_pages;

    var chkAll = document.getElementById('dc-check-all');
    if (chkAll) {
      chkAll.checked = state.items.length > 0 && state.items.every(function (x) { return state.selectedBatchKeys.has(x.doc_key); });
    }
  }

  function updateBatchBar() {
    var bar = document.getElementById('dc-batch-bar');
    var cnt = document.getElementById('dc-batch-count');
    if (!bar || !cnt) return;
    var n = state.selectedBatchKeys.size;
    cnt.textContent = String(n);
    bar.hidden = n === 0;
  }

  /* ── EXPEDIENTE DE 4 PESTAÑAS CON CANCELACIÓN DE SOLICITUDES ANTERIORES ── */
  async function openDocumentExpediente(docRef, pushHistory) {
    if (!docRef) return;
    if (pushHistory && state.activeDocId && state.activeDocId !== docRef) {
      state.docHistoryStack.push(state.activeDocId);
    }

    if (state.expAbort) state.expAbort.abort();
    var ctrl = new AbortController();
    state.expAbort = ctrl;

    var expAside = document.getElementById('dc-expediente');
    if (expAside) expAside.hidden = false;

    var backBtn = document.getElementById('dc-exp-back-history');
    if (backBtn) backBtn.hidden = state.docHistoryStack.length === 0;

    var stage = document.getElementById('dc-paper-stage');
    if (stage) {
      stage.innerHTML = '<div class="dc-state-box"><i class="fa-solid fa-spinner fa-spin"></i><span>Cargando expediente...</span></div>';
    }

    try {
      var exp = await dcFetch('/api/documents/item/' + encodeURIComponent(docRef), { signal: ctrl.signal });
      if (state.expAbort !== ctrl) return;

      state.activeExpediente = exp;
      state.activeDocId = exp.document.id;
      state.activeDocKey = exp.document.doc_key;

      // Resaltar fila activa sin reconstruir ni perder el listado
      document.querySelectorAll('.dc-doc-row, .dc-thumb-card').forEach(function (el) {
        el.classList.toggle('active', el.getAttribute('data-doc-key') === state.activeDocKey);
      });

      renderExpedienteContent(exp);
      loadExpedientePreview();
    } catch (err) {
      if (err && err.name === 'AbortError') return;
      if (stage) {
        stage.innerHTML = '<div class="dc-state-box"><i class="fa-solid fa-circle-exclamation" style="color:var(--dc-err-txt);"></i>' +
          '<strong>' + esc(err && err.status === 403 ? 'Acceso restringido' : 'No se pudo abrir el expediente') + '</strong>' +
          '<span>' + esc(err ? err.message : '') + '</span></div>';
      }
    }
  }

  function renderExpedienteContent(exp) {
    var doc = exp.document;
    var avail = exp.action_availability || {};

    var folEl = document.getElementById('dc-exp-folio');
    var stEl = document.getElementById('dc-exp-status-pill');
    var subEl = document.getElementById('dc-exp-subtype-lbl');
    var favBtn = document.getElementById('dc-exp-fav');
    if (folEl) folEl.textContent = doc.folio_visible;
    if (stEl) {
      stEl.className = 'dc-status-pill ' + statusBadgeClass(doc.doc_status);
      stEl.textContent = prettyStatus(doc.doc_status);
    }
    if (subEl) subEl.textContent = doc.subtype_label + ' · ' + doc.sucursal_id;
    if (favBtn) {
      favBtn.classList.toggle('fav-on', !!doc.is_favorite);
      favBtn.innerHTML = '<i class="' + (doc.is_favorite ? 'fa-solid' : 'fa-regular') + ' fa-star" aria-hidden="true"></i>';
    }

    // Barra inferior contextual del listado
    var ctxLbl = document.getElementById('dc-ctx-doc-label');
    var ctxOrig = document.getElementById('dc-ctx-open-origin');
    var ctxRel = document.getElementById('dc-ctx-open-related');
    if (ctxLbl) ctxLbl.textContent = doc.subtype_label + ' ' + doc.folio_visible;
    if (ctxOrig) ctxOrig.disabled = false;
    if (ctxRel) ctxRel.disabled = false;

    // Selector de formatos disponibles en pestaña Documento
    var fmtSel = document.getElementById('dc-preview-format');
    var fmts = doc.available_formats || [];
    if (fmtSel) {
      if (!fmts.length) {
        fmtSel.innerHTML = '<option value="">Sin representación autorizada</option>';
      } else {
        var keepCurrent = fmts.indexOf(state.preview.format) !== -1 ? state.preview.format : (exp.default_format || fmts[0]);
        state.preview.format = keepCurrent;
        fmtSel.innerHTML = fmts.map(function (f) {
          var lbl = f === 'CARTA' ? 'Carta' : (f === 'TICKET' ? 'Ticket 80mm' : (f === 'XML' ? 'XML firmado' : 'Acuse SAT'));
          return '<option value="' + esc(f) + '"' + (f === keepCurrent ? ' selected' : '') + '>' + esc(lbl) + '</option>';
        }).join('');
      }
    }
    state.preview.page = 1;

    // Adjuntos y enlaces en pestaña Documento
    var attLbl = document.getElementById('dc-upload-att-lbl');
    if (attLbl) attLbl.style.display = avail.can_attach ? 'inline-flex' : 'none';

    var attListEl = document.getElementById('dc-attachments-list');
    if (attListEl) {
      var atts = exp.attachments || [];
      if (!atts.length) {
        attListEl.innerHTML = '<div style="font-size:11.5px;color:var(--dc-muted);">Sin archivos adjuntos adicionales.</div>';
      } else {
        attListEl.innerHTML = atts.map(function (a) {
          var actBtn = a.restricted
            ? '<span class="dc-status-pill dc-st-neutral" title="' + esc(a.restriction_reason) + '"><i class="fa-solid fa-lock"></i> Protegido</span>'
            : '<button type="button" class="dc-pill-btn" data-dl-att="' + esc(a.id) + '" style="height:26px;font-size:11px;"><i class="fa-solid fa-download"></i> Descargar</button>';
          return '<div class="dc-rel-card">' +
            '<div style="min-width:0;"><div style="font-size:12px;font-weight:700;overflow:hidden;text-overflow:ellipsis;">' + esc(a.filename) + '</div>' +
            '<div style="font-size:10.5px;color:var(--dc-muted);">' + esc(a.kind) + ' · ' + Math.max(1, Math.round((a.size_bytes || 0) / 1024)) + ' KB</div></div>' +
            actBtn +
            '</div>';
        }).join('');
      }
    }

    // Pestaña 2: Datos completos + 4 estados independientes + Abrir movimiento original
    var datosEl = document.getElementById('dc-datos-container');
    if (datosEl) {
      var subTxt = doc.amount_state === 'NOT_APPLICABLE' ? 'No aplica' : (doc.amount_state === 'REDACTED' ? 'Reservado por rol' : fmtMoney(doc.subtotal, doc.currency));
      var taxTxt = doc.amount_state === 'NOT_APPLICABLE' ? 'No aplica' : (doc.amount_state === 'REDACTED' ? 'Reservado por rol' : fmtMoney(doc.tax_amount, doc.currency));
      var totTxt = doc.amount_state === 'NOT_APPLICABLE' ? 'No aplica' : (doc.amount_state === 'REDACTED' ? 'Reservado por rol' : (doc.amount_state === 'ZERO' ? fmtMoney(0, doc.currency) + ' (Importe cero)' : fmtMoney(doc.total_amount, doc.currency)));

      var cancelHtml = doc.cancel_reason
        ? '<div class="dc-rep-notice" style="background:var(--dc-err-bg);color:var(--dc-err-txt);border-color:rgba(239,68,68,.3);"><strong>Motivo de cancelación:</strong> ' + esc(doc.cancel_reason) + '</div>'
        : '';

      datosEl.innerHTML =
        cancelHtml +
        '<div style="font-size:11px;font-weight:800;text-transform:uppercase;color:var(--dc-muted);">Estados por separado</div>' +
        '<div class="dc-kv-grid">' +
          '<div class="dc-kv-box"><div class="dc-kv-lbl">Estado documental</div><div class="dc-kv-val"><span class="dc-status-pill ' + statusBadgeClass(doc.doc_status) + '">' + esc(prettyStatus(doc.doc_status)) + '</span></div></div>' +
          '<div class="dc-kv-box"><div class="dc-kv-lbl">Estado de pago</div><div class="dc-kv-val"><span class="dc-status-pill ' + statusBadgeClass(doc.payment_status) + '">' + esc(prettyStatus(doc.payment_status)) + '</span></div></div>' +
          '<div class="dc-kv-box"><div class="dc-kv-lbl">Estado fiscal</div><div class="dc-kv-val"><span class="dc-status-pill ' + statusBadgeClass(doc.fiscal_status) + '">' + esc(prettyStatus(doc.fiscal_status)) + '</span></div></div>' +
          '<div class="dc-kv-box"><div class="dc-kv-lbl">Estado de envío</div><div class="dc-kv-val"><span class="dc-status-pill ' + statusBadgeClass(doc.dispatch_status) + '">' + esc(prettyStatus(doc.dispatch_status)) + '</span></div></div>' +
        '</div>' +
        '<div style="font-size:11px;font-weight:800;text-transform:uppercase;color:var(--dc-muted);margin-top:4px;">Ficha de emisión</div>' +
        '<div class="dc-kv-grid">' +
          '<div class="dc-kv-box"><div class="dc-kv-lbl">Folio / Serie</div><div class="dc-kv-val">' + esc(doc.folio_visible) + (doc.serie ? ' (' + esc(doc.serie) + ')' : '') + '</div></div>' +
          '<div class="dc-kv-box"><div class="dc-kv-lbl">Emisión (' + esc(doc.branch_tz) + ')</div><div class="dc-kv-val">' + esc(doc.emitted_local || doc.emitted_at || '—') + '</div></div>' +
          '<div class="dc-kv-box"><div class="dc-kv-lbl">Sucursal origen</div><div class="dc-kv-val">' + esc(doc.sucursal_id) + '</div></div>' +
          '<div class="dc-kv-box"><div class="dc-kv-lbl">Caja / Terminal</div><div class="dc-kv-val">' + esc(doc.caja_id || 'No aplica') + '</div></div>' +
          '<div class="dc-kv-box"><div class="dc-kv-lbl">Emisor</div><div class="dc-kv-val">' + esc(doc.emisor_nombre || 'SISTEMA') + '</div></div>' +
          '<div class="dc-kv-box"><div class="dc-kv-lbl">Naturaleza</div><div class="dc-kv-val">' + esc(doc.doc_nature.replace(/_/g, ' ')) + '</div></div>' +
          '<div class="dc-kv-box" style="grid-column:1/-1;"><div class="dc-kv-lbl">Cliente / Proveedor / Sujeto</div><div class="dc-kv-val">' + esc(doc.tercero_nombre || '—') + (doc.tercero_rfc ? ' · RFC: ' + esc(doc.tercero_rfc) : '') + '</div></div>' +
          '<div class="dc-kv-box"><div class="dc-kv-lbl">Moneda / Subtotal</div><div class="dc-kv-val">' + esc(doc.currency) + ' · ' + esc(subTxt) + '</div></div>' +
          '<div class="dc-kv-box"><div class="dc-kv-lbl">Impuestos / Total</div><div class="dc-kv-val">' + esc(taxTxt) + ' / <strong>' + esc(totTxt) + '</strong></div></div>' +
          '<div class="dc-kv-box" style="grid-column:1/-1;"><div class="dc-kv-lbl">UUID / Referencia / Identidad interna</div><div class="dc-kv-val" style="font-size:11.5px;">' +
            (doc.uuid_fiscal ? 'UUID: ' + esc(doc.uuid_fiscal) + '<br>' : '') +
            'Ref: ' + esc(doc.reference_text || '—') + '<br><span style="color:var(--dc-muted);font-family:monospace;">ID: ' + esc(doc.doc_key) + '</span>' +
          '</div></div>' +
        '</div>' +
        '<button type="button" class="dc-btn" id="dc-datos-open-origin" style="width:100%;margin-top:4px;">' +
          '<i class="fa-solid fa-arrow-up-right-from-square" aria-hidden="true"></i> Abrir movimiento original en ' + esc((exp.movement_origin && exp.movement_origin.module_label) || 'módulo emisor') +
        '</button>';
    }

    // Pestaña 3: Relacionados
    var relBadge = document.getElementById('dc-rel-badge');
    var rels = exp.related || [];
    if (relBadge) relBadge.textContent = rels.length ? '(' + rels.length + ')' : '';

    var relEl = document.getElementById('dc-rel-container');
    if (relEl) {
      if (!rels.length) {
        relEl.innerHTML = '<div class="dc-state-box" style="padding:24px 12px;"><i class="fa-solid fa-link-slash"></i><span>Este documento no registra movimientos vinculados adicionales.</span></div>';
      } else {
        relEl.innerHTML = rels.map(function (r) {
          var amtStr = !r.amount_applicable ? '—' : (r.amount_redacted ? 'Reservado' : fmtMoney(r.total_amount, 'MXN'));
          if (!r.authorized) {
            return '<div class="dc-rel-card" title="' + esc(r.restriction_reason) + '">' +
              '<div><div style="font-size:12.5px;font-weight:700;">' + esc(r.folio_visible) + ' · ' + esc(r.relation_label) + '</div>' +
              '<div style="font-size:11px;color:var(--dc-muted);">' + esc(r.restriction_reason) + '</div></div>' +
              '<span class="dc-status-pill dc-st-neutral"><i class="fa-solid fa-lock"></i> Restringido</span></div>';
          }
          return '<div class="dc-rel-card clickable" tabindex="0" data-open-related="' + esc(r.doc_key) + '">' +
            '<div><div style="font-size:12.5px;font-weight:800;color:var(--dc-blue);">' + esc(r.folio_visible) + '</div>' +
            '<div style="font-size:11.5px;color:var(--dc-text-2);">' + esc(r.relation_label) + ' · ' + esc(r.sucursal_id) + '</div></div>' +
            '<div style="text-align:right;">' +
              '<div style="font-size:12px;font-weight:700;">' + esc(amtStr) + '</div>' +
              '<span class="dc-status-pill ' + statusBadgeClass(r.doc_status) + '" style="font-size:10px;padding:1px 7px;">' + esc(prettyStatus(r.doc_status)) + '</span>' +
            '</div></div>';
        }).join('');
      }
    }

    // Pestaña 4: Actividad
    var actEl = document.getElementById('dc-act-container');
    if (actEl) {
      var acts = exp.activity || [];
      actEl.innerHTML = acts.map(function (a) {
        var confPill = a.confirmed
          ? '<span class="dc-status-pill dc-st-ok" style="font-size:10px;padding:1px 7px;">Confirmado</span>'
          : '<span class="dc-status-pill dc-st-neutral" style="font-size:10px;padding:1px 7px;">Solicitud / Sin acuse</span>';
        return '<div class="dc-act-item" style="align-items:flex-start;flex-direction:column;gap:4px;">' +
          '<div style="display:flex;width:100%;justify-content:space-between;align-items:center;gap:6px;">' +
            '<strong style="font-size:12px;">' + esc(a.action) + '</strong>' + confPill +
          '</div>' +
          '<div style="font-size:11.5px;color:var(--dc-text-2);">' + esc(a.result) + '</div>' +
          '<div style="font-size:10.5px;color:var(--dc-muted);">' + esc(fmtShortDate(a.timestamp)) + ' · ' + esc(a.actor) + ' · Canal: ' + esc(a.channel) + '</div>' +
        '</div>';
      }).join('');
    }

    // Disponibilidad de botones fijos del Expediente
    var btnPr = document.getElementById('dc-exp-btn-print');
    var btnDl = document.getElementById('dc-exp-btn-download');
    var btnSd = document.getElementById('dc-exp-btn-send');
    var noteEl = document.getElementById('dc-exp-avail-note');
    if (btnPr) btnPr.disabled = !avail.can_print;
    if (btnDl) btnDl.disabled = !avail.can_download;
    if (btnSd) btnSd.disabled = !avail.can_send;
    if (noteEl) {
      noteEl.textContent = avail.disabled_reason ||
        ('Formatos disponibles: ' + ((doc.available_formats || []).join(', ') || 'Ninguno') +
         (doc.has_original_file ? ' · Original conservado' : ' · Reconstrucción desde origen'));
    }
  }

  /* ── CARGA BAJO DEMANDA DE LA VISTA PREVIA GRÁFICA / XML ── */
  async function loadExpedientePreview() {
    if (!state.activeExpediente || !state.activeDocId) return;
    var doc = state.activeExpediente.document;
    var stage = document.getElementById('dc-paper-stage');
    var notice = document.getElementById('dc-rep-notice');
    var pgBar = document.getElementById('dc-page-nav-bar');
    if (!stage) return;

    if (!doc.available_formats || !doc.available_formats.length) {
      if (pgBar) pgBar.hidden = true;
      if (notice) {
        notice.className = 'dc-rep-notice';
        notice.textContent = (state.activeExpediente.action_availability && state.activeExpediente.action_availability.disabled_reason) ||
          'Tu rol puede consultar los metadatos permitidos, pero las representaciones PDF/XML están protegidas para no revelar importes.';
      }
      stage.innerHTML = '<div class="dc-state-box"><i class="fa-solid fa-shield-halved"></i><strong>Vista previa protegida</strong><span>Los importes de este documento están reservados para tu rol.</span></div>';
      return;
    }

    if (state.previewAbort) state.previewAbort.abort();
    var ctrl = new AbortController();
    state.previewAbort = ctrl;

    var fmt = state.preview.format || 'CARTA';
    var rep = state.preview.representation || 'original';

    if (fmt === 'XML' || fmt === 'ACUSE') {
      if (pgBar) pgBar.hidden = true;
      stage.innerHTML = '<div class="dc-state-box"><i class="fa-solid fa-spinner fa-spin"></i><span>Cargando XML firmado...</span></div>';
      try {
        var resXml = await dcFetch('/api/documents/item/' + encodeURIComponent(state.activeDocId) + '/file?format=' + encodeURIComponent(fmt) + '&disposition=inline', { signal: ctrl.signal });
        var xmlTxt = await resXml.text();
        if (state.previewAbort !== ctrl) return;
        if (notice) {
          notice.className = 'dc-rep-notice conserved';
          notice.textContent = fmt === 'XML' ? 'XML CFDI 4.0 firmado original conservado íntegro.' : 'Acuse oficial de cancelación SAT.';
        }
        stage.innerHTML = '<pre class="dc-xml-pre">' + esc(xmlTxt) + '</pre>';
      } catch (err) {
        if (err && err.name === 'AbortError') return;
        stage.innerHTML = '<div class="dc-state-box"><i class="fa-solid fa-file-circle-xmark" style="color:var(--dc-err-txt);"></i><strong>Archivo faltante</strong><span>' + esc(err.message) + '</span></div>';
      }
      return;
    }

    stage.innerHTML = '<div class="dc-state-box"><i class="fa-solid fa-spinner fa-spin"></i><span>Renderizando formato ' + esc(fmt) + '...</span></div>';
    try {
      var q = new URLSearchParams({
        mode: fmt,
        representation: rep,
        page: String(state.preview.page || 1)
      });
      var prevData = await dcFetch('/api/documents/item/' + encodeURIComponent(state.activeDocId) + '/preview-page?' + q.toString(), { signal: ctrl.signal });
      if (state.previewAbort !== ctrl) return;

      state.preview.page = prevData.page || 1;
      state.preview.totalPages = prevData.total_pages || 1;
      var rmeta = prevData.representation_meta || {};

      if (pgBar) {
        pgBar.hidden = state.preview.totalPages <= 1;
        var pgLbl = document.getElementById('dc-preview-page-lbl');
        var bPrev = document.getElementById('dc-prev-pg');
        var bNext = document.getElementById('dc-next-pg');
        if (pgLbl) pgLbl.textContent = 'Página ' + state.preview.page + ' de ' + state.preview.totalPages;
        if (bPrev) bPrev.disabled = state.preview.page <= 1;
        if (bNext) bNext.disabled = state.preview.page >= state.preview.totalPages;
      }

      if (notice) {
        var cls = rmeta.is_conserved_original ? 'conserved' : (rmeta.is_reconstructed ? 'reconstructed' : '');
        notice.className = 'dc-rep-notice ' + cls;
        notice.textContent = rmeta.notice || 'Vista previa generada.';
      }

      var scalePct = state.preview.zoom || 100;
      stage.innerHTML = '<img id="dc-preview-img" src="' + prevData.image_data_uri + '" alt="Vista previa de ' + esc(doc.folio_visible) + '" style="width:' + scalePct + '%;max-width:none;">';
    } catch (err) {
      if (err && err.name === 'AbortError') return;
      stage.innerHTML = '<div class="dc-state-box"><i class="fa-solid fa-file-circle-exclamation" style="color:var(--dc-err-txt);"></i><strong>Vista previa no disponible</strong><span>' + esc(err ? err.message : '') + '</span></div>';
    }
  }

  function switchExpedienteTab(tabKey) {
    ['doc', 'datos', 'rel', 'act'].forEach(function (k) {
      var btn = document.getElementById('dc-tab-btn-' + k);
      var pnl = document.getElementById('dc-panel-' + k);
      var sel = k === tabKey;
      if (btn) btn.setAttribute('aria-selected', sel ? 'true' : 'false');
      if (pnl) pnl.hidden = !sel;
    });
  }

  /* ── IMPRESIÓN, DESCARGAS, LOTES ZIP Y EXPORTACIONES ── */
  function openPrintModalForDoc(docId) {
    if (docId && docId !== state.activeDocId) {
      openDocumentExpediente(docId, false).then(function () { openPrintModalNow(); });
    } else {
      openPrintModalNow();
    }
  }

  function openPrintModalNow() {
    if (!state.activeExpediente) return;
    var doc = state.activeExpediente.document;
    var fmtSel = document.getElementById('dc-pr-format');
    if (fmtSel) {
      var pdfFmts = (doc.available_formats || []).filter(function (f) { return f === 'CARTA' || f === 'TICKET'; });
      fmtSel.innerHTML = pdfFmts.map(function (f) {
        return '<option value="' + esc(f) + '"' + (f === state.preview.format ? ' selected' : '') + '>' + (f === 'CARTA' ? 'Tamaño Carta' : 'Ticket térmico 80mm') + '</option>';
      }).join('');
    }
    var prtSel = document.getElementById('dc-pr-printer');
    if (prtSel) {
      var prts = (state.boot && state.boot.printers) || [];
      var opts = '<option value="BROWSER">Diálogo del navegador (Solicitud de impresión)</option>';
      prts.forEach(function (p) {
        opts += '<option value="LOCAL:' + esc(p.name || p.model) + '">Impresora configurada: ' + esc(p.name) + ' (' + esc(p.width || '') + ')</option>';
      });
      prtSel.innerHTML = opts;
    }
    openDialog('dc-dialog-print');
  }

  async function executePrintAction() {
    if (!state.activeDocId) return;
    var fmt = (document.getElementById('dc-pr-format') || {}).value || 'CARTA';
    var rep = (document.getElementById('dc-pr-rep') || {}).value || 'original';
    var prtVal = (document.getElementById('dc-pr-printer') || {}).value || 'BROWSER';
    var copies = parseInt((document.getElementById('dc-pr-copies') || {}).value || '1', 10) || 1;

    var isLocalBridge = !!(global.CalebsysPrintAgent && typeof global.CalebsysPrintAgent.printPdf === 'function');
    var channel = (prtVal.indexOf('LOCAL:') === 0 && isLocalBridge) ? 'LOCAL_AGENT' : 'BROWSER_DIALOG';
    var prtName = prtVal.indexOf('LOCAL:') === 0 ? prtVal.slice(6) : 'DIÁLOGO DEL NAVEGADOR';

    try {
      var resPdf = await dcFetch('/api/documents/item/' + encodeURIComponent(state.activeDocId) + '/file?format=' + encodeURIComponent(fmt) + '&representation=' + encodeURIComponent(rep) + '&disposition=inline');
      var blob = await resPdf.blob();
      var pdfUrl = URL.createObjectURL(blob);

      var confirmed = false;
      if (channel === 'LOCAL_AGENT') {
        confirmed = !!(await global.CalebsysPrintAgent.printPdf(blob, { printer: prtName, copies: copies }));
      } else {
        var iframe = document.createElement('iframe');
        iframe.style.cssText = 'position:fixed;right:0;bottom:0;width:0;height:0;border:0;';
        iframe.src = pdfUrl;
        document.body.appendChild(iframe);
        iframe.onload = function () {
          try { iframe.contentWindow.focus(); iframe.contentWindow.print(); } catch (_) { window.open(pdfUrl, '_blank'); }
          setTimeout(function () { try { document.body.removeChild(iframe); } catch (_) {} }, 60000);
        };
      }

      var logRes = await dcFetch('/api/documents/item/' + encodeURIComponent(state.activeDocId) + '/print-log', {
        method: 'POST',
        body: JSON.stringify({
          channel: channel,
          format: fmt,
          copies: copies,
          printer_name: prtName,
          spooler_confirmed: confirmed
        })
      });
      closeDialog('dc-dialog-print');
      showToastMsg(logRes.registered_status + ': ' + logRes.detail, 'success');
      openDocumentExpediente(state.activeDocId, false);
    } catch (err) {
      showToastMsg(err.message || 'No se pudo preparar la impresión.', 'error');
    }
  }

  async function triggerAuthorizedDownload(docId, fmt, rep, attachmentId) {
    try {
      var q = new URLSearchParams({ format: fmt, representation: rep || 'original', disposition: 'attachment' });
      if (attachmentId) q.set('attachment_id', attachmentId);
      var res = await dcFetch('/api/documents/item/' + encodeURIComponent(docId) + '/file?' + q.toString());
      var cd = res.headers.get('content-disposition') || '';
      var m = cd.match(/filename="([^"]+)"/);
      var fname = m ? m[1] : ('DOCUMENTO_' + fmt + '.pdf');
      var blob = await res.blob();
      var url = URL.createObjectURL(blob);
      var a = document.createElement('a');
      a.href = url;
      a.download = fname;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      setTimeout(function () { URL.revokeObjectURL(url); }, 15000);
      showToastMsg('Descargado: ' + fname, 'success');
    } catch (err) {
      showToastMsg(err.message || 'Error al descargar archivo.', 'error');
    }
  }

  function openDownloadModal() {
    if (!state.activeExpediente) return;
    var doc = state.activeExpediente.document;
    var body = document.getElementById('dc-dlg-dl-body');
    if (!body) return;
    var fmts = doc.available_formats || [];
    var html = '<div style="font-size:12.5px;color:var(--dc-text-2);">Archivos autorizados con nomenclatura distinguida por <strong>Folio + Sucursal + Formato</strong>:</div>';
    html += '<div style="display:flex;flex-direction:column;gap:8px;">';
    fmts.forEach(function (f) {
      var ext = (f === 'XML' || f === 'ACUSE') ? 'xml' : 'pdf';
      var sampleName = doc.folio_visible + '_' + doc.sucursal_id + '_' + f + '.' + ext;
      html += '<div class="dc-rel-card">' +
        '<div><strong style="font-size:12.5px;color:var(--dc-text);">Formato ' + esc(f) + '</strong><div style="font-size:11px;color:var(--dc-muted);font-family:monospace;">' + esc(sampleName) + '</div></div>' +
        '<button type="button" class="dc-btn dc-btn-primary" data-dl-fmt="' + esc(f) + '" style="height:32px;font-size:12px;"><i class="fa-solid fa-download"></i> Descargar</button>' +
        '</div>';
    });
    html += '</div>';
    body.innerHTML = html;
    openDialog('dc-dialog-download');
  }

  async function executeBatchZipDownload() {
    var keys = Array.from(state.selectedBatchKeys);
    if (!keys.length) return;
    try {
      var res = await dcFetch('/api/documents/download-batch', {
        method: 'POST',
        body: JSON.stringify({ doc_keys: keys, preferred_mode: 'AUTO', include_xml: true })
      });
      if (res.included_count > 0 && res.zip_base64) {
        var bin = atob(res.zip_base64);
        var arr = new Uint8Array(bin.length);
        for (var i = 0; i < bin.length; i++) arr[i] = bin.charCodeAt(i);
        var blob = new Blob([arr], { type: 'application/zip' });
        var url = URL.createObjectURL(blob);
        var a = document.createElement('a');
        a.href = url;
        a.download = res.filename || 'LOTE_DOCUMENTOS.zip';
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        setTimeout(function () { URL.revokeObjectURL(url); }, 15000);
      }

      var body = document.getElementById('dc-dlg-dl-body');
      var title = document.getElementById('dc-dlg-dl-title');
      if (title) title.textContent = 'Resumen de descarga por lote (ZIP)';
      if (body) {
        var incHtml = (res.included || []).map(function (x) {
          return '<li style="color:var(--dc-ok-txt);">✓ <strong>' + esc(x.filename) + '</strong> (' + esc(x.representation) + ')</li>';
        }).join('');
        var failHtml = (res.failed || []).map(function (f) {
          return '<li style="color:var(--dc-err-txt);">✕ <strong>' + esc(f.folio || f.doc_key) + ':</strong> ' + esc(f.reason) + '</li>';
        }).join('');
        body.innerHTML =
          '<div><strong>Archivos incluidos (' + res.included_count + '):</strong><ul style="margin:6px 0 0 18px;font-size:12px;">' + (incHtml || '<li>Ninguno</li>') + '</ul></div>' +
          (res.failed_count > 0 ? '<div style="margin-top:8px;"><strong>Archivos con incidencia (' + res.failed_count + '):</strong><ul style="margin:6px 0 0 18px;font-size:12px;">' + failHtml + '</ul></div>' : '');
        openDialog('dc-dialog-download');
      }
    } catch (err) {
      showToastMsg(err.message || 'No se pudo generar el ZIP por lote.', 'error');
    }
  }

  async function executeExportOrReport() {
    var scope = (document.getElementById('dc-exp-scope') || {}).value || 'all_results';
    var fmt = (document.getElementById('dc-exp-format') || {}).value || 'csv';

    if (fmt === 'print') {
      closeDialog('dc-dialog-export');
      await printFilteredReport(scope);
      return;
    }

    try {
      var params = buildListQueryParams({ format: fmt, scope: scope });
      var res = await dcFetch('/api/documents/export?' + params.toString());
      var cd = res.headers.get('content-disposition') || '';
      var m = cd.match(/filename="([^"]+)"/);
      var fname = m ? m[1] : ('DOCUMENTOS.' + fmt);
      var blob = await res.blob();
      var url = URL.createObjectURL(blob);
      var a = document.createElement('a');
      a.href = url;
      a.download = fname;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      closeDialog('dc-dialog-export');
      showToastMsg('Listado exportado: ' + fname, 'success');
    } catch (err) {
      showToastMsg(err.message || 'No se pudo exportar el listado.', 'error');
    }
  }

  async function printFilteredReport(scope) {
    try {
      var params = buildListQueryParams({ scope: scope || 'current_page' });
      var rep = await dcFetch('/api/documents/report-print?' + params.toString());
      var prof = rep.company_profile || {};
      var rowsHtml = (rep.items || []).map(function (r) {
        var tot = !r.amount_applicable ? 'NO APLICA' : (r.amount_state === 'REDACTED' ? 'RESERVADO' : fmtMoney(r.total_amount, r.currency));
        return '<tr>' +
          '<td><strong>' + esc(r.folio_visible) + '</strong><br><small>' + esc(r.subtype_label) + '</small></td>' +
          '<td>' + esc(r.tercero_nombre || '—') + '</td>' +
          '<td>' + esc(r.sucursal_id) + '</td>' +
          '<td>' + esc(r.emitted_local || r.emitted_at || '') + '</td>' +
          (rep.view_amounts ? '<td style="text-align:right;font-weight:700;">' + esc(tot) + '</td>' : '') +
          '<td>' + esc(r.doc_status) + '</td>' +
        '</tr>';
      }).join('');

      var w = window.open('', '_blank', 'width=980,height=720');
      if (!w) {
        showToastMsg('Habilita las ventanas emergentes para imprimir el reporte.', 'warn');
        return;
      }
      w.document.write(
        '<!DOCTYPE html><html lang="es"><head><meta charset="utf-8"><title>Reporte Documental — ' + esc(prof.nombre_comercial || 'CALEBSYS') + '</title>' +
        '<style>body{font-family:Arial,sans-serif;padding:24px;color:#0f172a;}h1{margin:0;font-size:18px;}table{width:100%;border-collapse:collapse;margin-top:14px;font-size:12px;}th,td{border:1px solid #cbd5e1;padding:6px 8px;text-align:left;}th{background:#f1f5f9;}</style></head><body>' +
        '<h1>' + esc(prof.nombre_comercial || 'CALEBSYS') + ' — REPORTE DEL CENTRO DE DOCUMENTOS</h1>' +
        '<p style="margin:4px 0;font-size:12px;color:#475569;"><strong>Alcance seleccionado:</strong> ' + esc(rep.scope_label) + ' · Emitido por: ' + esc(rep.generated_by) + '</p>' +
        '<table><thead><tr><th>Folio / Tipo</th><th>Cliente / Proveedor</th><th>Sucursal</th><th>Emisión</th>' +
        (rep.view_amounts ? '<th style="text-align:right;">Total</th>' : '') +
        '<th>Estado</th></tr></thead><tbody>' + rowsHtml + '</tbody></table></body></html>'
      );
      w.document.close();
      w.focus();
      setTimeout(function () { w.print(); }, 350);
    } catch (err) {
      showToastMsg(err.message || 'No se pudo generar el reporte imprimible.', 'error');
    }
  }

  /* ── ENVÍOS INDIVIDUALES, LOTES, IDEMPOTENCIA Y ENLACES SEGUROS ── */
  function openSendModal(isBatch) {
    var targets = [];
    if (isBatch) {
      state.items.forEach(function (it) {
        if (state.selectedBatchKeys.has(it.doc_key)) {
          targets.push({
            doc_key: it.doc_key,
            id: it.id,
            folio_visible: it.folio_visible,
            tercero_nombre: it.tercero_nombre,
            recipient: '',
            formats: it.has_xml ? ['CARTA', 'XML'] : ['CARTA']
          });
        }
      });
    } else if (state.activeExpediente) {
      var d = state.activeExpediente.document;
      var c = state.activeExpediente.contact || {};
      targets.push({
        doc_key: d.doc_key,
        id: d.id,
        folio_visible: d.folio_visible,
        tercero_nombre: d.tercero_nombre,
        email: c.email || '',
        phone: c.phone || '',
        recipient: c.email || '',
        formats: d.has_xml ? ['CARTA', 'XML'] : [state.preview.format === 'TICKET' ? 'TICKET' : 'CARTA']
      });
    }
    if (!targets.length) return;

    state.dispatchSession = {
      operationKey: 'OP-' + Date.now() + '-' + Math.random().toString(36).slice(2, 9).toUpperCase(),
      operationId: null,
      targetEntries: targets
    };

    var resBox = document.getElementById('dc-sd-result-box');
    if (resBox) { resBox.hidden = true; resBox.innerHTML = ''; }
    var btnRet = document.getElementById('dc-sd-retry-failed');
    var btnRef = document.getElementById('dc-sd-refresh-provider');
    var btnConf = document.getElementById('dc-sd-confirm');
    if (btnRet) btnRet.hidden = true;
    if (btnRef) btnRef.hidden = true;
    if (btnConf) btnConf.hidden = false;

    renderSendModalChannelUI();
    openDialog('dc-dialog-send');
  }

  function renderSendModalChannelUI() {
    var ch = (document.getElementById('dc-sd-channel') || {}).value || 'EMAIL';
    var shareBox = document.getElementById('dc-sd-share-box');
    var dispBox = document.getElementById('dc-sd-dispatch-box');
    var modeWrap = document.getElementById('dc-sd-mode-wrap');
    var noteEl = document.getElementById('dc-sd-channel-note');
    var btnConf = document.getElementById('dc-sd-confirm');

    var chInfoMap = (state.boot && state.boot.channels) || {};
    var chKey = ch.toLowerCase();
    var info = chInfoMap[chKey] || {};
    if (noteEl) {
      noteEl.textContent = info.status_note || 'Verifica destinatario y archivos antes de confirmar.';
      // Si el canal real no tiene credenciales activas, sugerir automáticamente modo prueba de integración
      var tmSel = document.getElementById('dc-sd-testmode');
      if (tmSel && (ch === 'EMAIL' || ch === 'WHATSAPP_API' || ch === 'CONECT') && !info.configured) {
        tmSel.value = 'true';
      }
    }

    if (ch === 'SHARE_LINK') {
      if (shareBox) shareBox.hidden = false;
      if (dispBox) dispBox.style.display = 'none';
      if (modeWrap) modeWrap.style.display = 'none';
      if (btnConf) btnConf.hidden = true;
      renderExistingShareLinks();
      return;
    }

    if (shareBox) shareBox.hidden = true;
    if (dispBox) dispBox.style.display = 'flex';
    if (modeWrap) modeWrap.style.display = ch === 'WHATSAPP_WEB' ? 'none' : '';
    if (btnConf) {
      btnConf.hidden = false;
      btnConf.textContent = ch === 'WHATSAPP_WEB' ? 'Abrir WhatsApp' : 'Confirmar envío';
    }

    var ed = document.getElementById('dc-sd-recipients-editor');
    if (ed) {
      var placeholder = ch === 'EMAIL' ? 'cliente@dominio.com' : '+526151234567';
      ed.innerHTML = state.dispatchSession.targetEntries.map(function (t, idx) {
        var defVal = t.recipient || (ch === 'EMAIL' ? (t.email || '') : (t.phone || ''));
        t.recipient = defVal;
        return '<div style="display:grid;grid-template-columns:1.1fr 1.4fr;gap:8px;align-items:center;background:var(--dc-surface-2);padding:7px 10px;border-radius:8px;border:1px solid var(--dc-border);">' +
          '<div style="font-size:12px;color:var(--dc-text);"><strong>' + esc(t.folio_visible) + '</strong><div style="font-size:10.5px;color:var(--dc-muted);">' + esc(t.tercero_nombre || '') + '</div></div>' +
          '<input type="' + (ch === 'EMAIL' ? 'email' : 'text') + '" data-sd-rec-idx="' + idx + '" value="' + esc(defVal) + '" placeholder="' + esc(placeholder) + '" style="height:30px;padding:0 8px;border:1px solid var(--dc-border-strong);border-radius:6px;font-size:12px;background:var(--dc-surface);color:var(--dc-text);">' +
        '</div>';
      }).join('');
    }
    refreshDispatchPreview();
  }

  async function refreshDispatchPreview() {
    var sumEl = document.getElementById('dc-sd-preview-summary');
    if (!sumEl || !state.dispatchSession.targetEntries.length) return;
    var ch = (document.getElementById('dc-sd-channel') || {}).value || 'EMAIL';
    var msg = (document.getElementById('dc-sd-message') || {}).value || '';
    try {
      var prev = await dcFetch('/api/documents/dispatch/preview', {
        method: 'POST',
        body: JSON.stringify({
          channel: ch,
          message: msg.toUpperCase(),
          items: state.dispatchSession.targetEntries
        })
      });
      sumEl.innerHTML = (prev.recipients_summary || []).map(function (r) {
        return '<div style="border-bottom:1px dashed var(--dc-border);padding-bottom:5px;">' +
          '<div><strong>Destinatario:</strong> ' + esc(r.recipient || '(Pendiente capturar)') + ' · <strong>Canal:</strong> ' + esc(r.channel) + '</div>' +
          '<div style="color:var(--dc-text-2);"><strong>Archivos exactos:</strong> ' + esc((r.exact_files || []).join(', ')) + '</div>' +
          (prev.message_normalized ? '<div style="color:var(--dc-muted);"><strong>Mensaje:</strong> ' + esc(prev.message_normalized) + '</div>' : '') +
        '</div>';
      }).join('');
    } catch (err) {
      sumEl.innerHTML = '<span style="color:var(--dc-err-txt);">' + esc(err.message) + '</span>';
    }
  }

  async function confirmDispatchExecution() {
    var ch = (document.getElementById('dc-sd-channel') || {}).value || 'EMAIL';
    var isTest = ((document.getElementById('dc-sd-testmode') || {}).value === 'true') && ch !== 'WHATSAPP_WEB';
    var msgEl = document.getElementById('dc-sd-message');
    if (msgEl && msgEl.value) msgEl.value = msgEl.value.toUpperCase();
    var msg = msgEl ? msgEl.value : '';

    try {
      var res = await dcFetch('/api/documents/dispatch', {
        method: 'POST',
        body: JSON.stringify({
          operation_key: state.dispatchSession.operationKey,
          channel: ch,
          subject: 'DOCUMENTOS EMITIDOS — CALEBSYS',
          message: msg,
          is_test_mode: isTest,
          items: state.dispatchSession.targetEntries
        })
      });
      state.dispatchSession.operationId = res.operation_id;
      renderDispatchOperationResult(res);
      loadDocumentsList({ silent: true });
      if (state.activeDocId) openDocumentExpediente(state.activeDocId, false);
    } catch (err) {
      showToastMsg(err.message || 'No se pudo procesar el envío.', 'error');
    }
  }

  function renderDispatchOperationResult(res) {
    var box = document.getElementById('dc-sd-result-box');
    var btnRet = document.getElementById('dc-sd-retry-failed');
    var btnRef = document.getElementById('dc-sd-refresh-provider');
    if (!box) return;
    box.hidden = false;

    var hasRetryable = (res.items || []).some(function (i) { return i.safe_to_retry; });
    var hasUncertain = (res.items || []).some(function (i) { return i.status === 'UNCERTAIN'; });
    if (btnRet) btnRet.hidden = !hasRetryable;
    if (btnRef) btnRef.hidden = !hasUncertain;

    var scopeTag = res.is_test_mode
      ? '<span class="dc-status-pill dc-st-info">Prueba de integración (sin salida externa)</span>'
      : '<span class="dc-status-pill dc-st-ok">Canal operativo</span>';

    var itemsHtml = (res.items || []).map(function (it) {
      var waAction = '';
      if (it.whatsapp_open_url) {
        waAction = ' <a href="' + esc(it.whatsapp_open_url) + '" target="_blank" rel="noopener noreferrer" class="dc-link-btn">Abrir WhatsApp ↗</a>' +
                   ' <button type="button" class="dc-link-btn" data-wa-dl-key="' + esc(it.doc_key) + '">Descargar PDF para adjuntar</button>';
      }
      return '<div style="padding:5px 0;border-bottom:1px solid var(--dc-border);font-size:12px;">' +
        '<div><strong>' + esc(it.folio_visible) + '</strong> → ' + esc(it.recipient) + ' · <strong>' + esc(it.ui_status_label) + '</strong> (intento #' + esc(it.attempt_count) + ')' + waAction + '</div>' +
        (it.error_detail ? '<div style="color:var(--dc-err-txt);font-size:11px;">' + esc(it.error_detail) + '</div>' : '') +
      '</div>';
    }).join('');

    box.innerHTML =
      '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">' +
        '<strong>Resultado de operación (' + res.succeeded_items + '/' + res.total_items + ' exitosos)</strong>' + scopeTag +
      '</div>' + itemsHtml;
  }

  function renderExistingShareLinks() {
    var box = document.getElementById('dc-share-links-result');
    if (!box || !state.activeExpediente) return;
    var links = state.activeExpediente.share_links || [];
    if (!links.length) {
      box.innerHTML = '<div style="font-size:12px;color:var(--dc-muted);">No hay enlaces generados para este documento.</div>';
      return;
    }
    box.innerHTML = links.map(function (l) {
      var fullUrl = window.location.origin + l.share_path;
      var stHtml = l.revoked
        ? '<span class="dc-status-pill dc-st-err">Revocado</span>'
        : '<button type="button" class="dc-btn" data-revoke-link="' + esc(l.id) + '" style="height:26px;font-size:11px;color:var(--dc-err-txt);">Revocar</button>';
      return '<div class="dc-rel-card" style="margin-top:6px;">' +
        '<div style="min-width:0;font-size:11.5px;">' +
          '<div><strong>' + esc(l.format_code) + '</strong> · Descargas: ' + esc(l.download_count) + '/' + esc(l.max_downloads) + ' · Vence: ' + esc(fmtShortDate(l.expires_at)) + '</div>' +
          '<input type="text" readonly value="' + esc(fullUrl) + '" style="width:100%;font-size:11px;border:1px solid var(--dc-border-strong);border-radius:5px;padding:2px 6px;margin-top:3px;background:var(--dc-surface);color:var(--dc-text);">' +
        '</div>' + stHtml + '</div>';
    }).join('');
  }

  /* ── DIVISOR ARRASTRABLE PARA REDIMENSIONAR EL EXPEDIENTE ── */
  function setupExpedienteResizer() {
    var resizer = document.getElementById('dc-resizer');
    var root = document.getElementById('dc-root');
    if (!resizer || !root) return;

    var dragging = false;
    resizer.addEventListener('pointerdown', function (e) {
      dragging = true;
      resizer.setPointerCapture(e.pointerId);
      e.preventDefault();
    });
    resizer.addEventListener('pointermove', function (e) {
      if (!dragging) return;
      var newW = Math.max(350, Math.min(760, window.innerWidth - e.clientX - 24));
      state.ui.drawer_width = Math.round(newW);
      root.style.setProperty('--dc-drawer-w', state.ui.drawer_width + 'px');
    });
    resizer.addEventListener('pointerup', function () {
      if (!dragging) return;
      dragging = false;
      dcFetch('/api/documents/preferences', {
        method: 'PUT',
        body: JSON.stringify({ drawer_width: state.ui.drawer_width })
      }).catch(function () {});
    });
  }

  /* ── REGISTRO DE EVENTOS DOM Y TECLADO (100% CSP SAFE) ── */
  function bindEvents() {
    var root = document.getElementById('dc-root');
    if (!root || root.dataset.bound === '1') return;
    root.dataset.bound = '1';

    setupExpedienteResizer();

    // Regla global MAYÚSCULAS en inputs de negocio (.dc-upper-input)
    root.addEventListener('input', function (e) {
      if (e.target && e.target.classList && e.target.classList.contains('dc-upper-input')) {
        var pos = e.target.selectionStart;
        e.target.value = e.target.value.toUpperCase();
        try { e.target.setSelectionRange(pos, pos); } catch (_) {}
      }
    });

    // Cerrar cualquier <dialog> con data-close-dlg
    root.addEventListener('click', function (e) {
      var closeBtn = e.target.closest('[data-close-dlg]');
      if (closeBtn) {
        closeDialog(closeBtn.getAttribute('data-close-dlg'));
        return;
      }

      // Retry en tabla tras error
      if (e.target.closest('#dc-btn-retry-list')) {
        loadDocumentsList();
        return;
      }
      if (e.target.closest('#dc-empty-clear-btn') || e.target.closest('#dc-clear-all-filters')) {
        resetFilters();
        loadDocumentsList();
        return;
      }

      // Quitar chip individual
      var rmChip = e.target.closest('[data-remove-chip]');
      if (rmChip) {
        var fk = rmChip.getAttribute('data-remove-chip');
        state.filters[fk] = '';
        syncFilterInputsFromState();
        state.pagination.page = 1;
        renderLibraryAndCategories();
        loadDocumentsList();
        return;
      }

      // Pestaña rápida horizontal de categoría
      var qCat = e.target.closest('[data-qcat]');
      if (qCat) {
        var qcid = qCat.getAttribute('data-qcat') || '';
        state.activeSavedViewId = '';
        state.filters.view_preset = 'all';
        state.filters.category = qcid;
        state.filters.doc_subtype = '';
        state.pagination.page = 1;
        renderLibraryAndCategories();
        loadDocumentsList();
        return;
      }

      // Ordenar columnas de tabla (modern-web-guidance: sortable-table)
      var sortBtn = e.target.closest('.dc-sort-btn');
      if (sortBtn) {
        var sortKey = sortBtn.getAttribute('data-sort');
        var th = sortBtn.closest('th');
        var nextDir = (state.filters.sort_by === sortKey && state.filters.sort_dir === 'desc') ? 'asc' : 'desc';
        state.filters.sort_by = sortKey;
        state.filters.sort_dir = nextDir;
        document.querySelectorAll('#dc-thead-row th').forEach(function (h) { h.removeAttribute('aria-sort'); });
        if (th) th.setAttribute('aria-sort', nextDir === 'asc' ? 'ascending' : 'descending');
        announce('Ordenado por ' + sortBtn.textContent.trim() + ' ' + (nextDir === 'asc' ? 'ascendente' : 'descendente'));
        loadDocumentsList();
        return;
      }

      // Casilla de selección por lote (INDEPENDIENTE de abrir el expediente)
      var batchChk = e.target.closest('[data-batch-key]');
      if (batchChk) {
        e.stopPropagation();
        var bKey = batchChk.getAttribute('data-batch-key');
        if (batchChk.checked) state.selectedBatchKeys.add(bKey);
        else state.selectedBatchKeys.delete(bKey);
        updateBatchBar();
        return;
      }

      // Favorito en fila
      var favRowBtn = e.target.closest('[data-fav-id]');
      if (favRowBtn) {
        e.stopPropagation();
        toggleFavorite(favRowBtn.getAttribute('data-fav-id'));
        return;
      }

      // Imprimir rápido desde fila
      var qpBtn = e.target.closest('[data-quick-print]');
      if (qpBtn) {
        e.stopPropagation();
        openPrintModalForDoc(qpBtn.getAttribute('data-quick-print'));
        return;
      }

      // Abrir expediente al elegir una fila o tarjeta de miniatura
      var rowEl = e.target.closest('.dc-doc-row, .dc-thumb-card');
      if (rowEl && !e.target.closest('input[type="checkbox"]')) {
        openDocumentExpediente(rowEl.getAttribute('data-doc-id'), false);
        return;
      }

      // Pestañas del expediente
      var expTab = e.target.closest('[data-exptab]');
      if (expTab) {
        switchExpedienteTab(expTab.getAttribute('data-exptab'));
        return;
      }

      // Abrir documento relacionado
      var relCard = e.target.closest('[data-open-related]');
      if (relCard) {
        openDocumentExpediente(relCard.getAttribute('data-open-related'), true);
        return;
      }

      // Descargar formato desde modal de descargas
      var dlFmtBtn = e.target.closest('[data-dl-fmt]');
      if (dlFmtBtn && state.activeDocId) {
        triggerAuthorizedDownload(state.activeDocId, dlFmtBtn.getAttribute('data-dl-fmt'), state.preview.representation);
        return;
      }

      // Descargar adjunto
      var dlAttBtn = e.target.closest('[data-dl-att]');
      if (dlAttBtn && state.activeDocId) {
        triggerAuthorizedDownload(state.activeDocId, 'ATTACHMENT', 'original', dlAttBtn.getAttribute('data-dl-att'));
        return;
      }

      // Descargar PDF para adjuntar manualmente en WhatsApp Web
      var waDl = e.target.closest('[data-wa-dl-key]');
      if (waDl) {
        triggerAuthorizedDownload(waDl.getAttribute('data-wa-dl-key'), 'CARTA', 'original');
        return;
      }

      // Revocar enlace compartido
      var revBtn = e.target.closest('[data-revoke-link]');
      if (revBtn) {
        dcFetch('/api/documents/share-links/' + encodeURIComponent(revBtn.getAttribute('data-revoke-link')) + '/revoke', { method: 'POST' })
          .then(function () {
            showToastMsg('Enlace revocado inmediatamente.', 'success');
            if (state.activeDocId) openDocumentExpediente(state.activeDocId, false).then(renderExistingShareLinks);
          });
        return;
      }

      // Abrir movimiento original desde pestaña Datos
      if (e.target.closest('#dc-datos-open-origin') || e.target.closest('#dc-ctx-open-origin')) {
        goToOriginalMovement();
        return;
      }
    });

    // Controles puntuales
    var searchTimer = null;
    var searchIn = document.getElementById('dc-search-input');
    var searchClr = document.getElementById('dc-search-clear');
    if (searchIn) {
      searchIn.addEventListener('input', function () {
        state.filters.q = searchIn.value.trim();
        if (searchClr) searchClr.hidden = !state.filters.q;
        clearTimeout(searchTimer);
        searchTimer = setTimeout(function () {
          state.pagination.page = 1;
          loadDocumentsList();
        }, 200);
      });
    }
    if (searchClr) {
      searchClr.addEventListener('click', function () {
        searchIn.value = '';
        state.filters.q = '';
        searchClr.hidden = true;
        state.pagination.page = 1;
        loadDocumentsList();
      });
    }

    var branchSel = document.getElementById('dc-branch-select');
    if (branchSel) {
      branchSel.addEventListener('change', function () {
        state.filters.sucursal_id = branchSel.value;
        state.pagination.page = 1;
        loadDocumentsList();
      });
    }

    var qSub = document.getElementById('dc-quick-subtype');
    if (qSub) {
      qSub.addEventListener('change', function () {
        state.filters.doc_subtype = qSub.value;
        state.pagination.page = 1;
        renderLibraryAndCategories();
        loadDocumentsList();
      });
    }

    var qPer = document.getElementById('dc-quick-period');
    if (qPer) {
      qPer.addEventListener('change', function () {
        var val = qPer.value;
        var now = new Date();
        function isoDay(d) { return d.toISOString().slice(0, 10); }
        if (val === 'today') {
          var td = (state.metrics && state.metrics.today_local_date) || isoDay(now);
          state.filters.date_from = td;
          state.filters.date_to = td;
        } else if (val === '7d') {
          var d7 = new Date(now.getTime() - 6 * 86400000);
          state.filters.date_from = isoDay(d7);
          state.filters.date_to = isoDay(now);
        } else if (val === '30d') {
          var d30 = new Date(now.getTime() - 29 * 86400000);
          state.filters.date_from = isoDay(d30);
          state.filters.date_to = isoDay(now);
        } else if (val === 'custom') {
          var mf = document.getElementById('dc-more-filters-panel');
          if (mf) mf.hidden = false;
          return;
        } else {
          state.filters.date_from = '';
          state.filters.date_to = '';
        }
        syncFilterInputsFromState();
        state.pagination.page = 1;
        loadDocumentsList();
      });
    }

    var qStat = document.getElementById('dc-quick-status');
    if (qStat) {
      qStat.addEventListener('change', function () {
        state.filters.doc_status = qStat.value;
        state.pagination.page = 1;
        loadDocumentsList();
      });
    }

    // Más filtros
    var btnMore = document.getElementById('dc-btn-more-filters');
    if (btnMore) {
      btnMore.addEventListener('click', function () {
        var pnl = document.getElementById('dc-more-filters-panel');
        if (pnl) {
          pnl.hidden = !pnl.hidden;
          btnMore.setAttribute('aria-expanded', pnl.hidden ? 'false' : 'true');
        }
      });
    }

    ['dc-f-from', 'dc-f-to', 'dc-f-emisor', 'dc-f-nature', 'dc-f-currency', 'dc-f-min', 'dc-f-max', 'dc-f-fiscal', 'dc-f-dispatch'].forEach(function (id) {
      var el = document.getElementById(id);
      if (!el) return;
      el.addEventListener('change', function () {
        state.filters.date_from = (document.getElementById('dc-f-from') || {}).value || '';
        state.filters.date_to = (document.getElementById('dc-f-to') || {}).value || '';
        state.filters.emisor = ((document.getElementById('dc-f-emisor') || {}).value || '').trim().toUpperCase();
        state.filters.doc_nature = (document.getElementById('dc-f-nature') || {}).value || '';
        state.filters.currency = (document.getElementById('dc-f-currency') || {}).value || '';
        state.filters.importe_min = (document.getElementById('dc-f-min') || {}).value || '';
        state.filters.importe_max = (document.getElementById('dc-f-max') || {}).value || '';
        state.filters.fiscal_status = (document.getElementById('dc-f-fiscal') || {}).value || '';
        state.filters.dispatch_status = (document.getElementById('dc-f-dispatch') || {}).value || '';
        state.pagination.page = 1;
        loadDocumentsList();
      });
    });

    // Clic rápido en cifra de Envíos con error
    var errChip = document.getElementById('dc-metric-errors');
    if (errChip) {
      errChip.addEventListener('click', function () {
        state.filters.dispatch_status = 'CON_ERROR';
        syncFilterInputsFromState();
        state.pagination.page = 1;
        loadDocumentsList();
      });
    }
    var helpBtn = document.getElementById('dc-btn-metrics-help');
    if (helpBtn) {
      helpBtn.addEventListener('click', function () {
        var hb = document.getElementById('dc-metrics-help-box');
        if (hb) hb.hidden = !hb.hidden;
      });
    }

    var svSel = document.getElementById('dc-saved-view-select');
    if (svSel) {
      svSel.addEventListener('change', function () {
        var val = svSel.value || 'preset:all';
        if (val.indexOf('preset:') === 0) {
          state.activeSavedViewId = '';
          state.filters.view_preset = val.slice(7) || 'all';
          state.filters.category = '';
          state.filters.doc_subtype = '';
          state.pagination.page = 1;
          renderLibraryAndCategories();
          loadDocumentsList();
        } else if (val.indexOf('view:') === 0) {
          var vid = val.slice(5);
          var svs = (state.boot && state.boot.preferences && state.boot.preferences.saved_views) || [];
          var foundV = svs.find(function (x) { return String(x.id) === vid; });
          if (foundV && foundV.filters) {
            state.activeSavedViewId = vid;
            state.filters = Object.assign(state.filters, foundV.filters);
            state.pagination.page = 1;
            syncFilterInputsFromState();
            renderLibraryAndCategories();
            loadDocumentsList();
          }
        }
      });
    }

    var svDelBtn = document.getElementById('dc-btn-del-saved-view');
    if (svDelBtn) {
      svDelBtn.addEventListener('click', function () {
        if (!state.activeSavedViewId) return;
        var dvid = state.activeSavedViewId;
        state.activeSavedViewId = '';
        dcFetch('/api/documents/views/' + encodeURIComponent(dvid), { method: 'DELETE' }).then(function (r) {
          if (state.boot && state.boot.preferences) {
            state.boot.preferences.saved_views = r.saved_views || [];
          }
          renderLibraryAndCategories();
          showToastMsg('Vista guardada eliminada.', 'info');
        });
      });
    }

    // Lista/Miniaturas y Paginación
    document.getElementById('dc-view-list').addEventListener('click', function () {
      state.ui.view_mode = 'list';
      applyUiSurfaceAndPrefs();
      dcFetch('/api/documents/preferences', { method: 'PUT', body: JSON.stringify({ view_mode: 'list' }) }).catch(function () {});
    });
    document.getElementById('dc-view-grid').addEventListener('click', function () {
      state.ui.view_mode = 'grid';
      applyUiSurfaceAndPrefs();
      setupLazyThumbnailsObserver();
      dcFetch('/api/documents/preferences', { method: 'PUT', body: JSON.stringify({ view_mode: 'grid' }) }).catch(function () {});
    });

    document.getElementById('dc-page-prev').addEventListener('click', function () {
      if (state.pagination.page > 1) {
        state.pagination.page -= 1;
        loadDocumentsList();
      }
    });
    document.getElementById('dc-page-next').addEventListener('click', function () {
      if (state.pagination.page < state.pagination.total_pages) {
        state.pagination.page += 1;
        loadDocumentsList();
      }
    });

    document.getElementById('dc-check-all').addEventListener('change', function (e) {
      var chk = e.target.checked;
      state.items.forEach(function (it) {
        if (chk) state.selectedBatchKeys.add(it.doc_key);
        else state.selectedBatchKeys.delete(it.doc_key);
      });
      renderTableAndThumbnails();
      applyUiSurfaceAndPrefs();
    });

    document.getElementById('dc-btn-batch-clear').addEventListener('click', function () {
      state.selectedBatchKeys.clear();
      renderTableAndThumbnails();
      applyUiSurfaceAndPrefs();
    });
    document.getElementById('dc-btn-batch-zip').addEventListener('click', executeBatchZipDownload);
    document.getElementById('dc-btn-batch-send').addEventListener('click', function () { openSendModal(true); });

    // Controles del Expediente
    document.getElementById('dc-exp-close').addEventListener('click', function () {
      document.getElementById('dc-expediente').hidden = true;
    });
    document.getElementById('dc-exp-expand').addEventListener('click', function () {
      root.classList.toggle('exp-expanded');
    });
    document.getElementById('dc-exp-dock-toggle').addEventListener('click', function () {
      state.ui.overlay_mode = !state.ui.overlay_mode;
      applyUiSurfaceAndPrefs();
    });
    document.getElementById('dc-exp-fav').addEventListener('click', function () {
      if (state.activeDocId) toggleFavorite(state.activeDocId);
    });
    document.getElementById('dc-exp-back-history').addEventListener('click', function () {
      var prevId = state.docHistoryStack.pop();
      if (prevId) openDocumentExpediente(prevId, false);
    });
    document.getElementById('dc-ctx-open-related').addEventListener('click', function () {
      document.getElementById('dc-expediente').hidden = false;
      switchExpedienteTab('rel');
    });

    document.getElementById('dc-preview-format').addEventListener('change', function (e) {
      state.preview.format = e.target.value;
      state.preview.page = 1;
      loadExpedientePreview();
    });
    document.getElementById('dc-preview-rep').addEventListener('change', function (e) {
      state.preview.representation = e.target.value;
      state.preview.page = 1;
      loadExpedientePreview();
    });
    document.getElementById('dc-zoom-in').addEventListener('click', function () {
      state.preview.zoom = Math.min(200, (state.preview.zoom || 100) + 20);
      document.getElementById('dc-zoom-lbl').textContent = state.preview.zoom + ' %';
      var img = document.getElementById('dc-preview-img');
      if (img) img.style.width = state.preview.zoom + '%';
    });
    document.getElementById('dc-zoom-out').addEventListener('click', function () {
      state.preview.zoom = Math.max(60, (state.preview.zoom || 100) - 20);
      document.getElementById('dc-zoom-lbl').textContent = state.preview.zoom + ' %';
      var img = document.getElementById('dc-preview-img');
      if (img) img.style.width = state.preview.zoom + '%';
    });
    document.getElementById('dc-prev-pg').addEventListener('click', function () {
      if (state.preview.page > 1) { state.preview.page -= 1; loadExpedientePreview(); }
    });
    document.getElementById('dc-next-pg').addEventListener('click', function () {
      if (state.preview.page < state.preview.totalPages) { state.preview.page += 1; loadExpedientePreview(); }
    });

    // Subida de archivo adjunto validado
    document.getElementById('dc-att-file-input').addEventListener('change', async function (e) {
      var file = e.target.files && e.target.files[0];
      e.target.value = '';
      if (!file || !state.activeDocId) return;
      var fd = new FormData();
      fd.append('file', file);
      fd.append('kind', 'EVIDENCIA');
      fd.append('contains_amounts', 'true');
      try {
        await dcFetch('/api/documents/item/' + encodeURIComponent(state.activeDocId) + '/attachments', {
          method: 'POST',
          body: fd
        });
        showToastMsg('Adjunto validado e integrado al expediente.', 'success');
        openDocumentExpediente(state.activeDocId, false);
      } catch (err) {
        showToastMsg(err.message || 'No se pudo adjuntar el archivo.', 'error');
      }
    });

    // Botonera principal del Expediente y Encabezado
    document.getElementById('dc-exp-btn-print').addEventListener('click', openPrintModalNow);
    document.getElementById('dc-exp-btn-download').addEventListener('click', openDownloadModal);
    document.getElementById('dc-exp-btn-send').addEventListener('click', function () { openSendModal(false); });
    document.getElementById('dc-pr-confirm').addEventListener('click', executePrintAction);

    document.getElementById('dc-btn-open-export').addEventListener('click', function () {
      document.getElementById('dc-exp-format').value = 'csv';
      openDialog('dc-dialog-export');
    });
    document.getElementById('dc-btn-print-report').addEventListener('click', function () {
      document.getElementById('dc-exp-format').value = 'print';
      openDialog('dc-dialog-export');
    });
    document.getElementById('dc-exp-confirm').addEventListener('click', executeExportOrReport);

    // Guardar vista
    document.getElementById('dc-btn-save-view').addEventListener('click', function () {
      document.getElementById('dc-sv-name').value = '';
      openDialog('dc-dialog-save-view');
    });
    document.getElementById('dc-sv-confirm').addEventListener('click', async function () {
      var nameEl = document.getElementById('dc-sv-name');
      var vName = (nameEl ? nameEl.value : '').trim().toUpperCase();
      if (!vName) return;
      try {
        var r = await dcFetch('/api/documents/views', {
          method: 'POST',
          body: JSON.stringify({ name: vName, filters: state.filters })
        });
        state.boot.preferences.saved_views = r.saved_views || [];
        if (state.boot.preferences.saved_views.length) {
          state.activeSavedViewId = String(state.boot.preferences.saved_views[state.boot.preferences.saved_views.length - 1].id);
        }
        closeDialog('dc-dialog-save-view');
        renderLibraryAndCategories();
        showToastMsg('Vista guardada: ' + vName, 'success');
      } catch (err) {
        showToastMsg(err.message, 'error');
      }
    });

    // Preferencias de columnas y densidad
    document.getElementById('dc-btn-prefs').addEventListener('click', function () {
      document.getElementById('dc-pref-density').value = state.ui.density || 'comfortable';
      var curCols = new Set(state.ui.columns || []);
      document.querySelectorAll('#dc-pref-cols input[type="checkbox"]').forEach(function (cb) {
        if (!cb.disabled) cb.checked = curCols.has(cb.value);
      });
      openDialog('dc-dialog-prefs');
    });
    document.getElementById('dc-pref-save').addEventListener('click', async function () {
      var cols = ['folio'];
      document.querySelectorAll('#dc-pref-cols input[type="checkbox"]:checked').forEach(function (cb) {
        if (cols.indexOf(cb.value) === -1) cols.push(cb.value);
      });
      state.ui.density = document.getElementById('dc-pref-density').value;
      state.ui.columns = cols;
      applyUiSurfaceAndPrefs();
      closeDialog('dc-dialog-prefs');
      await dcFetch('/api/documents/preferences', { method: 'PUT', body: JSON.stringify(state.ui) }).catch(function () {});
    });

    // Eventos del modal Enviar
    document.getElementById('dc-sd-channel').addEventListener('change', renderSendModalChannelUI);
    document.getElementById('dc-sd-recipients-editor').addEventListener('input', function (e) {
      var idx = e.target.getAttribute('data-sd-rec-idx');
      if (idx !== null && state.dispatchSession.targetEntries[idx]) {
        state.dispatchSession.targetEntries[idx].recipient = e.target.value.trim();
        refreshDispatchPreview();
      }
    });
    document.getElementById('dc-sd-message').addEventListener('change', refreshDispatchPreview);
    document.getElementById('dc-sd-confirm').addEventListener('click', confirmDispatchExecution);
    document.getElementById('dc-sd-retry-failed').addEventListener('click', async function () {
      if (!state.dispatchSession.operationId) return;
      try {
        var r = await dcFetch('/api/documents/dispatch/' + encodeURIComponent(state.dispatchSession.operationId) + '/retry', { method: 'POST', body: '{}' });
        renderDispatchOperationResult(r);
        loadDocumentsList({ silent: true });
      } catch (err) {
        showToastMsg(err.message, 'error');
      }
    });
    document.getElementById('dc-sd-refresh-provider').addEventListener('click', async function () {
      if (!state.dispatchSession.operationId) return;
      try {
        var r = await dcFetch('/api/documents/dispatch/' + encodeURIComponent(state.dispatchSession.operationId) + '/refresh-status', { method: 'POST' });
        renderDispatchOperationResult(r);
      } catch (err) {
        showToastMsg(err.message, 'error');
      }
    });
    document.getElementById('dc-btn-create-share').addEventListener('click', async function () {
      if (!state.activeDocKey) return;
      try {
        await dcFetch('/api/documents/share-links', {
          method: 'POST',
          body: JSON.stringify({
            doc_key: state.activeDocKey,
            format_code: document.getElementById('dc-sh-fmt').value,
            expires_in_hours: parseInt(document.getElementById('dc-sh-hours').value, 10) || 24,
            max_downloads: parseInt(document.getElementById('dc-sh-max').value, 10) || 5
          })
        });
        await openDocumentExpediente(state.activeDocId, false);
        renderExistingShareLinks();
        showToastMsg('Enlace temporal generado.', 'success');
      } catch (err) {
        showToastMsg(err.message, 'error');
      }
    });

    document.getElementById('dc-btn-sync-index').addEventListener('click', async function () {
      await dcFetch('/api/documents/sync', { method: 'POST', body: '{}' }).catch(function () {});
      await initDocumentCenter();
      showToastMsg('Índice documental sincronizado con origen.', 'success');
    });

    // Navegación completa por teclado (Ctrl+K, Flechas en filas, Enter, Escape)
    document.addEventListener('keydown', function (e) {
      if (!document.getElementById('dc-root')) return;
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        var sIn = document.getElementById('dc-search-input');
        if (sIn) sIn.focus();
        return;
      }
      if (e.key === 'Escape') {
        var openDlg = document.querySelector('dialog.dc-dialog[open]');
        if (!openDlg) {
          var expEl = document.getElementById('dc-expediente');
          if (expEl && !expEl.hidden) expEl.hidden = true;
        }
        return;
      }
      var activeRow = document.activeElement && document.activeElement.closest('.dc-doc-row');
      if (activeRow) {
        if (e.key === 'Enter') {
          e.preventDefault();
          openDocumentExpediente(activeRow.getAttribute('data-doc-id'), false);
        } else if (e.key === 'ArrowDown' && activeRow.nextElementSibling) {
          e.preventDefault();
          activeRow.nextElementSibling.focus();
        } else if (e.key === 'ArrowUp' && activeRow.previousElementSibling) {
          e.preventDefault();
          activeRow.previousElementSibling.focus();
        }
      }
    });
  }

  async function toggleFavorite(docId) {
    try {
      var res = await dcFetch('/api/documents/favorites/' + encodeURIComponent(docId), { method: 'POST' });
      state.items.forEach(function (it) {
        if (it.doc_key === res.doc_key) it.is_favorite = res.is_favorite;
      });
      if (state.boot && state.boot.library) state.boot.library.favorites_count = res.favorites_count;
      if (state.activeExpediente && state.activeExpediente.document.doc_key === res.doc_key) {
        state.activeExpediente.document.is_favorite = res.is_favorite;
        renderExpedienteContent(state.activeExpediente);
      }
      renderLibraryAndCategories();
      renderTableAndThumbnails();
      applyUiSurfaceAndPrefs();
    } catch (err) {
      showToastMsg(err.message, 'error');
    }
  }

  function goToOriginalMovement() {
    if (!state.activeExpediente || !state.activeExpediente.movement_origin) return;
    saveReturnState();
    var orig = state.activeExpediente.movement_origin;
    if (typeof global.navigateTo === 'function' && orig.page_id) {
      global.navigateTo(orig.page_id);
    } else if (orig.url) {
      window.location.href = orig.url;
    }
  }

  function resetFilters() {
    var defaultSuc = (state.boot && state.boot.branches && state.boot.branches.default_branch) || 'ALL';
    state.activeSavedViewId = '';
    state.filters = {
      q: '', view_preset: 'all', category: '', doc_subtype: '',
      sucursal_id: defaultSuc, emisor: '', doc_nature: '', currency: '',
      importe_min: '', importe_max: '', doc_status: '', fiscal_status: '',
      dispatch_status: '', date_from: '', date_to: '', sort_by: 'emitted_at', sort_dir: 'desc'
    };
    state.pagination.page = 1;
    syncFilterInputsFromState();
    renderLibraryAndCategories();
  }

  function syncFilterInputsFromState() {
    var f = state.filters;
    var map = {
      'dc-search-input': f.q,
      'dc-branch-select': f.sucursal_id,
      'dc-quick-status': f.doc_status,
      'dc-f-from': f.date_from,
      'dc-f-to': f.date_to,
      'dc-f-emisor': f.emisor,
      'dc-f-nature': f.doc_nature,
      'dc-f-currency': f.currency,
      'dc-f-min': f.importe_min,
      'dc-f-max': f.importe_max,
      'dc-f-fiscal': f.fiscal_status,
      'dc-f-dispatch': f.dispatch_status
    };
    Object.keys(map).forEach(function (id) {
      var el = document.getElementById(id);
      if (el) el.value = map[id] !== undefined && map[id] !== null ? map[id] : '';
    });
  }

  /* ── PUNTO DE ENTRADA PRINCIPAL DEL MÓDULO ── */
  async function initDocumentCenter() {
    bindEvents();
    try {
      var boot = await dcFetch('/api/documents/bootstrap');
      state.boot = boot;

      // Datos reales de la sesión (empresa, logotipo, sucursal)
      var prof = (boot.session && boot.session.company_profile) || {};
      var chipLbl = document.getElementById('dc-session-label');
      var chipLogo = document.getElementById('dc-session-logo');
      var chipIco = document.getElementById('dc-session-ico');
      if (chipLbl) {
        chipLbl.textContent = (prof.nombre_comercial || boot.session.empresa_id) + ' · ' + (boot.session.session_sucursal || 'MATRIZ');
      }
      if (chipLogo && prof.logotipo) {
        chipLogo.src = prof.logotipo;
        chipLogo.hidden = false;
        if (chipIco) chipIco.hidden = true;
      }

      // Poblar UN SOLO selector de sucursal según permisos de sesión
      var bSel = document.getElementById('dc-branch-select');
      if (bSel && boot.branches) {
        var bHtml = '';
        if (boot.branches.can_select_all) {
          bHtml += '<option value="ALL">Todas las sucursales</option>';
        }
        (boot.branches.options || []).forEach(function (b) {
          bHtml += '<option value="' + esc(b.id) + '">' + esc(b.name) + '</option>';
        });
        bSel.innerHTML = bHtml;
        bSel.disabled = !boot.branches.can_select_all && (boot.branches.options || []).length <= 1;
        state.filters.sucursal_id = boot.branches.default_branch || 'ALL';
        bSel.value = state.filters.sucursal_id;
      }

      // Ocultar filtros de importe si el rol no tiene permiso `view_amounts`
      var canViewAmounts = !!(boot.permissions && boot.permissions.view_amounts);
      var minW = document.getElementById('dc-fld-min-wrap');
      var maxW = document.getElementById('dc-fld-max-wrap');
      if (minW) minW.style.display = canViewAmounts ? '' : 'none';
      if (maxW) maxW.style.display = canViewAmounts ? '' : 'none';

      //Ocultar botones globales de exportar/imprimir si no tiene permiso
      var btnExp = document.getElementById('dc-btn-open-export');
      var btnPrt = document.getElementById('dc-btn-print-report');
      if (btnExp) btnExp.disabled = !(boot.permissions && boot.permissions.export);
      if (btnPrt) btnPrt.disabled = !(boot.permissions && boot.permissions.print);

      // Preferencias guardadas del usuario
      if (boot.preferences && boot.preferences.ui_prefs) {
        state.ui = Object.assign(state.ui, boot.preferences.ui_prefs);
      }

      // En 1366x768 activar modo superpuesto por defecto si aún no se configuró
      if (window.innerWidth <= 1420 && boot.preferences && boot.preferences.ui_prefs && boot.preferences.ui_prefs.overlay_mode === undefined) {
        state.ui.overlay_mode = true;
      }

      var restored = tryRestoreReturnState();
      syncFilterInputsFromState();
      renderLibraryAndCategories();
      applyUiSurfaceAndPrefs();

      await loadDocumentsList({
        sync: false,
        restoreDocKey: restored ? restored.activeDocKey : null,
        restoreScrollTop: restored ? restored.scrollTop : null
      });

      // Si hay documentos y ancho de escritorio (>= 1280px) y aún no hay expediente abierto, abrir el primero como en la referencia
      if (!restored && state.items.length > 0 && window.innerWidth >= 1280 && !state.activeDocId) {
        openDocumentExpediente(state.items[0].id, false);
      }
    } catch (err) {
      renderErrorStateInTable(err);
    }
  }

  global.loadDocumentos = initDocumentCenter;
  if (!global.pageInitHandlers) global.pageInitHandlers = {};
  global.pageInitHandlers['documentos'] = initDocumentCenter;

})(window);
