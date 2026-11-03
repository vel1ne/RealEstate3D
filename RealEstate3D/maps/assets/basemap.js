/* Optional OSM background. Respect genuine browser identity and normal HTTP cache.
   Never display an HTTP error body as a tile or retry a blocked service. */
(function (root) {
  'use strict';
  function attachBasemap(options) {
    const L = options.L, map = options.map, checkbox = options.checkbox, status = options.status;
    const protocol = options.protocol === undefined ? root.location.protocol : options.protocol;
    const fetchTile = options.fetchImpl || root.fetch.bind(root);
    const document = options.document || root.document;
    const urls = options.urlApi || root.URL;
    const Abort = options.AbortController || root.AbortController;
    const active = new Set();
    let stopped = false, layer = null;
    const offMessage = 'Онлайн-фон выключен. Дороги, поиск и ограничения доступны без него.';
    function show(message, error) {
      status.textContent = message;
      status.classList.toggle('basemap-warning', Boolean(error));
    }
    checkbox.checked = false;
    if (protocol !== 'http:' && protocol !== 'https:') {
      checkbox.disabled = true;
      show('Карта открыта как файл. Для онлайн-фона запустите «Открыть карту.cmd» в папке RealEstate3D. Дорожный слой уже работает.', false);
      return { isBlocked: () => false, layer: null };
    }
    function cleanup(tile) {
      if (tile._mapRequest) { tile._mapRequest.abort(); tile._mapRequest = null; }
      if (tile._mapObjectUrl) { urls.revokeObjectURL(tile._mapObjectUrl); tile._mapObjectUrl = null; }
      tile.onload = null;
      tile.onerror = null;
      active.delete(tile);
    }
    function cancelAll() { Array.from(active).forEach(cleanup); }
    function blockBackground(error) {
      if (stopped) return;
      stopped = true;
      checkbox.checked = false;
      checkbox.disabled = true;
      cancelAll();
      if (layer && map.hasLayer(layer)) map.removeLayer(layer);
      const code = error && error.httpStatus;
      show(code === 403 || code === 429
        ? 'Сервис фоновой карты отказал в доступе. Онлайн-фон отключён; дороги, поиск и ограничения продолжают работать.'
        : 'Онлайн-фон недоступен. Дороги, поиск и ограничения продолжают работать без него.', true);
    }
    const CheckedTiles = L.TileLayer.extend({
      createTile: function (coords, done) {
        const tile = document.createElement('img');
        tile.alt = '';
        tile.setAttribute('role', 'presentation');
        if (stopped || !checkbox.checked) return tile;
        const request = new Abort();
        tile._mapRequest = request;
        active.add(tile);
        let settled = false;
        function finish(error) {
          if (settled) return;
          settled = true;
          done(error || null, tile);
        }
        const fail = error => {
          if (request.signal.aborted || stopped) return;
          finish(error);
          blockBackground(error);
        };
        fetchTile(this.getTileUrl(coords), {
          signal: request.signal,
          mode: 'cors',
          credentials: 'omit',
          cache: 'default',
          referrerPolicy: 'strict-origin-when-cross-origin'
        }).then(response => {
          if (!response.ok) {
            const error = new Error('Background HTTP ' + response.status);
            error.httpStatus = response.status;
            throw error;
          }
          const type = response.headers.get('content-type') || '';
          if (!type.toLowerCase().startsWith('image/')) throw new Error('Background is not an image');
          return response.blob();
        }).then(blob => {
          if (request.signal.aborted || stopped || !checkbox.checked) return;
          const objectUrl = urls.createObjectURL(blob);
          tile._mapObjectUrl = objectUrl;
          tile.onload = function () {
            if (request.signal.aborted || stopped) return;
            urls.revokeObjectURL(objectUrl);
            tile._mapObjectUrl = null;
            show('Онлайн-фон включён. Цветные линии поверх него — дорожный слой проекта.', false);
            finish(null);
          };
          tile.onerror = function () { fail(new Error('Background image could not be decoded')); };
          tile.src = objectUrl;
        }).catch(fail);
        return tile;
      }
    });
    layer = new CheckedTiles('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19,
      keepBuffer: 0,
      updateWhenIdle: true,
      updateWhenZooming: false,
      attribution: '© <a href="https://www.openstreetmap.org/copyright">Участники OpenStreetMap</a>'
    });
    layer.on('tileunload', event => cleanup(event.tile));
    layer.on('remove', cancelAll);
    checkbox.addEventListener('change', function () {
      if (stopped) { checkbox.checked = false; return; }
      if (checkbox.checked) {
        show('Загружается онлайн-фон…', false);
        layer.addTo(map);
      } else {
        cancelAll();
        if (map.hasLayer(layer)) map.removeLayer(layer);
        show(offMessage, false);
      }
    });
    show(offMessage, false);
    return { isBlocked: () => stopped, layer };
  }
  root.attachBasemap = attachBasemap;
  if (typeof module !== 'undefined' && module.exports) module.exports = { attachBasemap };
}(typeof window !== 'undefined' ? window : globalThis));
