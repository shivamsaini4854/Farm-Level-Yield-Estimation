const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

class Element {
  constructor(tag = 'div') { this.tagName = tag; this.children = []; this.style = {}; this.dataset = {}; this.listeners = {}; this.value = ''; this.disabled = false; this._text = ''; this.classes = new Set(); this.classList = {add: c => this.classes.add(c), remove: c => this.classes.delete(c)}; }
  set textContent(value) { this._text = String(value); this.children = []; }
  get textContent() { return this._text + this.children.map(child => child.textContent).join(''); }
  set innerHTML(value) { assert.equal(value, '', 'Dynamic HTML is forbidden in results'); this.replaceChildren(); }
  append(...items) { this.children.push(...items); }
  replaceChildren(...items) { this.children = items; this._text = ''; }
  addEventListener(name, callback) { this.listeners[name] = callback; }
  click() { if (!this.disabled && this.listeners.click) return this.listeners.click.call(this); }
}

const nodes = new Map();
const get = id => { if (!nodes.has(id)) nodes.set(id, new Element()); return nodes.get(id); };
const crops = ['Wheat', 'Rice'].map(crop => { const e = new Element('button'); e.dataset.crop = crop; return e; });
const app = new Element();
const document = {querySelector: () => app, getElementById: get,
  querySelectorAll: selector => selector === '.crop-btn' ? crops : [], createElement: tag => new Element(tag)};
const mapEvents = {};
let polygonCount = 0;
const removedLayers = [];
const map = {on: (event, callback) => {mapEvents[event] = callback;}, fitBounds() {}, getZoom: () => 12,
  setView() {}, flyTo() {}, removeLayer(layer) {removedLayers.push(layer);}, invalidateSize() {}};
const addable = () => ({addTo() {return this;}, on() {}});
const districtLayer = addable();
let allowDistrict = false;
let districtRenderCount = 0;
const L = {latLngBounds: () => ({}), map: () => map, control: {zoom: addable}, tileLayer: addable,
  divIcon: () => ({}), marker: addable, polygon: () => {polygonCount++; return addable();},
  geoJSON: () => {assert.ok(allowDistrict, 'A stale district response was rendered'); districtRenderCount++; return districtLayer;}};
const pending = [];
let exported;
const fetch = url => url === '/api/predictions' ? Promise.resolve({ok: true, json: async () => ({predictions: []})}) :
  new Promise(resolve => pending.push({url, resolve}));
const context = {document, L, fetch, AbortController, Blob, URL: {createObjectURL: blob => {exported = blob; return 'blob:fixture';}, revokeObjectURL() {}},
  window: {addEventListener() {}}, alert() {}, setInterval, clearInterval, clearTimeout,
  setTimeout: (callback, delay) => {const timer = setTimeout(callback, delay); timer.unref(); return timer;}};
vm.runInNewContext(fs.readFileSync('farm_yield/static/js/app.js', 'utf8'), context);
const tick = () => new Promise(resolve => setImmediate(resolve));
const clickMap = (lat, lng) => mapEvents.click({latlng: {lat, lng}});

(async () => {
  await tick();
  clickMap(30, 77);
  get('analyze-btn').click();
  assert.equal(pending.length, 1);
  crops[1].click();
  pending.shift().resolve({ok: true, json: async () => ({prediction: 999})});
  await tick();
  assert.equal(get('result-cards').children.length, 0, 'An old crop response must not render');
  assert.equal(get('result-cards').style.display, 'none');

  get('analyze-btn').click();
  pending.shift().resolve({ok: false, json: async () => ({error: '<img src=x onerror=alert(1)>'})});
  await tick();
  assert.match(get('result-cards').textContent, /<img src=x onerror=alert\(1\)>/);
  assert.equal(get('result-cards').children[0].children[1].tagName, 'p');

  get('draw-outline').click();
  clickMap(30.00, 77.00);
  clickMap(30.01, 77.00);
  assert.equal(get('finish-outline').disabled, true);
  clickMap(30.01, 77.01);
  assert.equal(get('finish-outline').disabled, false);
  get('finish-outline').click();
  get('export-outline').click();
  const feature = JSON.parse(await exported.text());
  assert.equal(feature.geometry.type, 'Polygon');
  assert.deepEqual(feature.geometry.coordinates[0], [[77, 30], [77, 30.01], [77.01, 30.01], [77, 30]]);
  assert.match(feature.properties.evidence, /do not validate field-level/);
  assert.equal(polygonCount, 3);

  get('district-layer').click();
  const request = pending.shift();
  crops[0].click();
  request.resolve({ok: true, json: async () => ({features: []})});
  await tick();
  allowDistrict = true;
  get('district-layer').click();
  pending.shift().resolve({ok: true, json: async () => ({features: []})});
  await tick();
  get('draw-outline').click();
  assert.ok(removedLayers.includes(districtLayer), 'Drawing must hide district popups that intercept corner clicks');
  assert.equal(get('district-layer').disabled, true);
  get('clear-outline').click();
  assert.equal(get('district-layer').disabled, false);
  get('district-layer').click();
  const beforeDrawing = pending.shift();
  get('draw-outline').click();
  beforeDrawing.resolve({ok: true, json: async () => ({features: []})});
  await tick();
  assert.equal(districtRenderCount, 1, 'A pending district layer must not appear over outline drawing');
  console.log('PASS: stale responses, safe text, GeoJSON export and outline/backtest isolation');
})().catch(error => {console.error(error); process.exitCode = 1;});
