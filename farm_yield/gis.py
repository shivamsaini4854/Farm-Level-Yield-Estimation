"""Create reproducible district coverage and backtest layers with a real QGIS layout."""

import csv
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def build_layers():
    geo = ROOT / 'data' / 'geo'
    boundaries = json.loads((geo / 'adm2.geojson').read_text(encoding='utf-8'))
    with (geo / 'district_locations.csv').open(encoding='utf-8', newline='') as stream:
        accepted = {r['shape_id']: r for r in csv.DictReader(stream)}
    coverage = {'type': 'FeatureCollection', 'features': []}
    for feature in boundaries['features']:
        properties = feature['properties']
        coverage['features'].append({**feature, 'properties': {
            'district': properties['shapeName'], 'shape_id': properties['shapeID'],
            'accepted': int(properties['shapeID'] in accepted)}})
    (geo / 'coverage.geojson').write_text(json.dumps(coverage), encoding='utf-8')
    current = ROOT / 'artifacts' / 'current.json'
    if not current.exists():
        return
    manifest = json.loads(current.read_text(encoding='utf-8'))
    directory = ROOT / 'artifacts' / 'runs' / manifest['run_id']
    metadata = json.loads((directory / 'metadata.json').read_text(encoding='utf-8'))
    with (directory / 'predictions.csv').open(encoding='utf-8', newline='') as stream:
        rows = [row for row in csv.DictReader(stream) if row['harvest_year'] == '2019']
    from farm_yield.seasons import CROPS
    for index, crop in enumerate(CROPS):
        estimates = {r['shape_id']: r for r in rows if r['Crop'] == crop}
        features = []
        for feature in boundaries['features']:
            row = estimates.get(feature['properties']['shapeID'])
            if row:
                features.append({'type': 'Feature', 'geometry': feature['geometry'], 'properties': {
                    'state': row['State'], 'district': row['District'], 'crop': crop,
                    'harvest_year': 2019, 'prediction_t_ha': float(row[metadata['model_name']]),
                    'observed_t_ha': float(row['Yield']), 'model_version': metadata['run_id'],
                    'evaluation_unit': 'district', 'evidence': 'retrospective backtest'}})
        (geo / f'yield_map_{index}.geojson').write_text(json.dumps({'type': 'FeatureCollection', 'features': features,
            'attribution': 'geoBoundaries gbOpen India ADM2; Pathways Data Pvt. Ltd.; lgdirectory.gov.in',
            'license': 'https://opendatacommons.org/licenses/odbl/1-0/'}), encoding='utf-8')


def render():
    import os
    os.environ['QT_QPA_PLATFORM'] = 'offscreen'
    from qgis.core import (Qgis, QgsApplication, QgsCategorizedSymbolRenderer,
        QgsLayoutExporter, QgsLayoutItemLabel, QgsLayoutItemLegend, QgsLayoutItemMap,
        QgsLayoutPoint, QgsLayoutSize, QgsPrintLayout, QgsProject, QgsRendererCategory,
        QgsSymbol, QgsVectorLayer, QgsGraduatedSymbolRenderer, QgsRendererRange, QgsSingleSymbolRenderer)
    from qgis.PyQt.QtGui import QFontDatabase, QFont
    application = QgsApplication([], True)
    application.initQgis()
    font_file = Path('C:/Windows/Fonts/arial.ttf')
    if font_file.exists():
        assert QFontDatabase.addApplicationFont(str(font_file)) >= 0
    assert QFontDatabase.families(), 'QGIS has no usable fonts.'
    project = QgsProject.instance()
    layer = QgsVectorLayer(str(ROOT / 'data/geo/coverage.geojson'), 'District evidence coverage', 'ogr')
    assert layer.isValid() and layer.featureCount() > 700
    categories = []
    for value, label, color in [(1, 'Accepted district/weather point', '#22955a'), (0, 'Unresolved or no eligible labels', '#d6d9dd')]:
        symbol = QgsSymbol.defaultSymbol(layer.geometryType())
        symbol.symbolLayer(0).setStrokeWidth(.05)
        from qgis.PyQt.QtGui import QColor
        symbol.setColor(QColor(color))
        categories.append(QgsRendererCategory(value, symbol, label))
    layer.setRenderer(QgsCategorizedSymbolRenderer('accepted', categories))
    project.addMapLayer(layer)
    layers = [layer]
    heading, image_name = 'Farm Yield | district evidence coverage', 'district_coverage.png'
    from farm_yield.seasons import CROPS
    wheat_path = ROOT / 'data/geo' / f"yield_map_{CROPS.index('Wheat')}.geojson"
    if wheat_path.exists():
        wheat = QgsVectorLayer(str(wheat_path), 'Wheat 2019 prediction (t/ha)', 'ogr')
        assert wheat.isValid() and wheat.featureCount() > 0
        maximum = float(wheat.maximumValue(wheat.fields().indexOf('prediction_t_ha')))
        ranges = []
        edges = [0, 1, 2, 3, 4, max(5, maximum + .001)]
        for index, color in enumerate(('#ffffcc', '#c2e699', '#78c679', '#31a354', '#006837')):
            symbol = QgsSymbol.defaultSymbol(wheat.geometryType())
            symbol.setColor(QColor(color))
            symbol.symbolLayer(0).setStrokeWidth(.05)
            label = f'{edges[index]:g}–{edges[index + 1]:.1f} t/ha'
            ranges.append(QgsRendererRange(edges[index], edges[index + 1], symbol, label))
        wheat.setRenderer(QgsGraduatedSymbolRenderer('prediction_t_ha', ranges))
        background = QgsSymbol.defaultSymbol(layer.geometryType())
        background.setColor(QColor('#e5e5e5'))
        background.symbolLayer(0).setStrokeWidth(.05)
        layer.setRenderer(QgsSingleSymbolRenderer(background))
        layer.setName('District boundaries (gray: no Wheat estimate)')
        project.addMapLayer(wheat)
        layers = [wheat, layer]
        heading, image_name = 'Farm Yield | Wheat 2019 district backtest', 'wheat_backtest.png'
    project.setCrs(layer.crs())
    project.setFilePathStorage(Qgis.FilePathType.Relative)
    layout = QgsPrintLayout(project)
    layout.initializeDefaults()
    page = layout.pageCollection().page(0)
    page.setPageSize('A4')
    title = QgsLayoutItemLabel(layout)
    title.setFont(QFont('Arial', 11))
    title.setText(heading)
    title.attemptMove(QgsLayoutPoint(12, 8))
    title.attemptResize(QgsLayoutSize(185, 12))
    layout.addLayoutItem(title)
    map_item = QgsLayoutItemMap(layout)
    map_item.attemptMove(QgsLayoutPoint(12, 25))
    map_item.attemptResize(QgsLayoutSize(185, 185))
    map_item.setLayers(layers)
    map_item.zoomToExtent(layer.extent())
    layout.addLayoutItem(map_item)
    legend = QgsLayoutItemLegend(layout)
    from qgis.core import QgsLegendStyle
    for style in (QgsLegendStyle.Style.Title, QgsLegendStyle.Style.Group,
                  QgsLegendStyle.Style.Subgroup, QgsLegendStyle.Style.SymbolLabel):
        legend.setStyleFont(style, QFont('Arial', 9))
    legend.setTitle('District retrospective estimates' if len(layers) > 1 else 'Geographic join audit')
    legend.setLinkedMap(map_item)
    legend.attemptMove(QgsLayoutPoint(12, 214))
    layout.addLayoutItem(legend)
    note = QgsLayoutItemLabel(layout)
    note.setFont(QFont('Arial', 8))
    note.setText('Boundaries: geoBoundaries / Pathways Data / LG Directory, ODbL 1.0.\n'
                 'District labels; reference-point features. Field-level accuracy unverified.\n'
                 'Coverage exclusions are explicit; this map is not a field prediction.')
    note.attemptMove(QgsLayoutPoint(12, 275))
    note.attemptResize(QgsLayoutSize(185, 20))
    layout.addLayoutItem(note)
    layout.setName('Wheat backtest' if len(layers) > 1 else 'District coverage')
    project.layoutManager().addLayout(layout)
    output = ROOT / 'docs' / 'gis'
    output.mkdir(exist_ok=True, parents=True)
    assert project.write(str(output / 'farm_yield.qgz'))
    settings = QgsLayoutExporter.ImageExportSettings()
    settings.dpi = 150
    settings.exportMetadata = False
    status = QgsLayoutExporter(layout).exportToImage(str(output / image_name), settings)
    assert status == QgsLayoutExporter.ExportResult.Success, status
    (output / 'render_evidence.json').write_text(json.dumps({'qgis_version': Qgis.QGIS_VERSION,
        'district_features': layer.featureCount(), 'render_status': int(status),
        'project': 'farm_yield.qgz', 'image': image_name,
        'yield_features': layers[0].featureCount() if len(layers) > 1 else 0}, indent=2), encoding='utf-8')
    print('PASS: real QGIS project and map image exported: ' + image_name)


if __name__ == '__main__':
    build_layers()
    render()
