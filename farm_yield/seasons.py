"""Fixed season conventions shared by acquisition, training, and serving."""

from datetime import date, timedelta


CROPS = (
    'Rice', 'Maize', 'Moong(Green Gram)', 'Urad', 'Groundnut', 'Wheat',
    'Rapeseed &Mustard', 'Sugarcane', 'Arhar/Tur', 'Potato', 'Onion',
    'Gram', 'Jowar', 'Dry chillies', 'Bajra', 'Soyabean',
)
CROP_SEASONS = {crop: 'Kharif' for crop in CROPS}
CROP_SEASONS.update({crop: 'Rabi' for crop in
                     ('Wheat', 'Rapeseed &Mustard', 'Potato', 'Onion', 'Gram')})
CROP_SEASONS['Sugarcane'] = 'Whole Year'


def season_dates(season, harvest_year):
    if season == 'Rabi':
        return date(harvest_year - 1, 10, 1), date(harvest_year, 3, 31)
    if season == 'Kharif':
        return date(harvest_year, 6, 1), date(harvest_year, 11, 30)
    if season == 'Whole Year':
        return date(harvest_year, 1, 1), date(harvest_year, 12, 31)
    if season == 'Summer':
        return date(harvest_year, 3, 1), date(harvest_year, 6, 30)
    raise ValueError('Unsupported season; its dates must be verified before use.')


def completed_season(crop, today=None):
    if crop not in CROP_SEASONS:
        raise ValueError('Unsupported crop.')
    available = (today or date.today()) - timedelta(days=5)
    year = available.year
    season = CROP_SEASONS[crop]
    start, end = season_dates(season, year)
    if end > available:
        year -= 1
        start, end = season_dates(season, year)
    return start, end, season, year


def season_months(start, end):
    current = start.replace(day=1)
    while current <= end:
        yield current
        current = date(current.year + (current.month == 12), current.month % 12 + 1, 1)
