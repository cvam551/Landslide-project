"""Sample Earth Engine catalog datasets at one lon/lat, or save satellite pngs.

Each source is a catalog entry. sample() takes source names and runs the same
reduceRegion for every one. dump_images() writes one png per satellite.
Dataset ids and bands are from the Earth Engine data catalog.
"""

from datetime import date
import os
from pathlib import Path
import urllib.request

# Pass these names to sample(). A new dataset is a new entry, not a new module.
SOURCES = {
    "elevation": {
        "id": "USGS/SRTMGL1_003",
        "band": "elevation",
        "scale": 30,
        "kind": "image",
    },
    "slope": {
        "id": "USGS/SRTMGL1_003",
        "band": "slope",
        "scale": 30,
        "kind": "terrain",
        "terrain": "slope",
    },
    "aspect": {
        "id": "USGS/SRTMGL1_003",
        "band": "aspect",
        "scale": 30,
        "kind": "terrain",
        "terrain": "aspect",
    },
    "precipitation": {
        "id": "UCSB-CHG/CHIRPS/DAILY",
        "band": "precipitation",
        "scale": 5566,
        "kind": "collection",
        "aggregate": "sum",
        "dated": True,
    },
    "ndvi": {
        "id": "MODIS/061/MOD13Q1",
        "band": "NDVI",
        "scale": 250,
        "kind": "collection",
        "aggregate": "mean",
        "scale_factor": 0.0001,
        "dated": True,
    },
    # WorldCover is tiled. mosaic() is the class at the point; collection.first() is an arbitrary tile.
    # Map codes: 10 tree, 20 shrub, 30 grass, 40 crop, 50 built, 60 bare, 70 snow, 80 water, 90 wetland, 95 mangrove, 100 moss.
    "landcover": {
        "id": "ESA/WorldCover/v200",
        "band": "Map",
        "scale": 10,
        "kind": "collection",
        "aggregate": "mosaic",
    },
}

# VV is already decibels. Optical min/max match the catalog quicklooks.
IMAGES = {
    "sentinel2": {
        "id": "COPERNICUS/S2_SR_HARMONIZED",
        "bands": ["B4", "B3", "B2"],
        "min": 0,
        "max": 3000,
        "cloud": "CLOUDY_PIXEL_PERCENTAGE",
    },
    "sentinel1": {
        "id": "COPERNICUS/S1_GRD",
        "bands": ["VV"],
        "min": -25,
        "max": 5,
        "mode": "IW",
        "polarization": "VV",
    },
    "landsat": {
        "ids": ["LANDSAT/LC08/C02/T1_L2", "LANDSAT/LC09/C02/T1_L2"],
        "bands": ["SR_B4", "SR_B3", "SR_B2"],
        "min": 0,
        "max": 0.3,
        "scale": 0.0000275,
        "offset": -0.2,
        "cloud": "CLOUD_COVER",
    },
    "modis": {
        "ids": ["MODIS/061/MOD09GA", "MODIS/061/MYD09GA"],
        "bands": ["sur_refl_b01", "sur_refl_b04", "sur_refl_b03"],
        "min": -100,
        "max": 8000,
        "cloud_band": "state_1km",
    },
}


def choose(names=None, start=None, end=None):
    """Return catalog names, or raise if a name or a required date window is wrong."""
    if names is None:
        picked = list(SOURCES)
    else:
        if isinstance(names, str):
            names = names.split(",")
        picked = [name.strip() for name in names if name.strip()]
    unknown = [name for name in picked if name not in SOURCES]
    if unknown:
        known = ", ".join(SOURCES)
        raise ValueError(f"unknown source: {', '.join(unknown)}; choose from {known}")
    if start or end:
        if not (start and end):
            raise ValueError("pass both start and end as YYYY-MM-DD")
        date.fromisoformat(start)
        date.fromisoformat(end)
        if start > end:
            raise ValueError("start must be on or before end")
    need = [name for name in picked if SOURCES[name].get("dated")]
    if need and not start:
        raise ValueError(f"{', '.join(need)} need start and end (YYYY-MM-DD)")
    return picked


def sample(lon, lat, sources=None, start=None, end=None, project=None):
    """Return {source: value} for one point.

    shortcut: one pixel via Reducer.first; a polygon needs mean or mode.
    """
    names = choose(sources, start, end)
    if not -180 <= lon <= 180 or not -90 <= lat <= 90:
        raise ValueError("lon must be -180..180 and lat -90..90")
    ee = _client(project)
    point = ee.Geometry.Point([lon, lat])
    values = {}
    for name in names:
        spec = SOURCES[name]
        image = _image(ee, spec, point, start, end)
        values[name] = image.reduceRegion(ee.Reducer.first(), point, spec["scale"]).get(spec["band"])
    return ee.Dictionary(values).getInfo()


def _client(project):
    import ee

    project = project or os.environ.get("EE_PROJECT")
    if not project:
        raise RuntimeError("Set EE_PROJECT or pass project=. That Cloud project must have the Earth Engine API enabled.")
    ee.Initialize(project=project)
    return ee


def choose_images(names=None, start=None, end=None):
    """Return satellite names. A date window is required."""
    if names is None:
        picked = list(IMAGES)
    else:
        if isinstance(names, str):
            names = names.split(",")
        picked = [name.strip() for name in names if name.strip()]
    unknown = [name for name in picked if name not in IMAGES]
    if unknown:
        known = ", ".join(IMAGES)
        raise ValueError(f"unknown image: {', '.join(unknown)}; choose from {known}")
    if not (start and end):
        raise ValueError("images need start and end (YYYY-MM-DD)")
    date.fromisoformat(start)
    date.fromisoformat(end)
    if start > end:
        raise ValueError("start must be on or before end")
    return picked


def dump_images(lon, lat, folder, start, end, images=None, project=None):
    """Write one png per satellite into folder. Returns the file paths.

    shortcut: least-cloudy optical scene and earliest radar scene, 5 km box, png not a geotiff. MODIS pixels are 500 m.
    """
    names = choose_images(images, start, end)
    if not -180 <= lon <= 180 or not -90 <= lat <= 90:
        raise ValueError("lon must be -180..180 and lat -90..90")
    ee = _client(project)
    region = ee.Geometry.Point([lon, lat]).buffer(5000)
    out = Path(folder)
    out.mkdir(parents=True, exist_ok=True)
    saved = []
    for name in names:
        image = _scene(ee, name, region, start, end)
        url = image.getThumbURL({
            "region": region,
            "dimensions": 768,
            "format": "png",
            "min": IMAGES[name]["min"],
            "max": IMAGES[name]["max"],
            "bands": IMAGES[name]["bands"],
        })
        path = out / f"{name}_{start}_{end}.png"
        with urllib.request.urlopen(url, timeout=180) as response:
            path.write_bytes(response.read())
        saved.append(path)
    return saved


def _scene(ee, name, region, start, end):
    spec = IMAGES[name]
    if spec.get("ids"):
        col = ee.ImageCollection(spec["ids"][0])
        for dataset_id in spec["ids"][1:]:
            col = col.merge(ee.ImageCollection(dataset_id))
    else:
        col = ee.ImageCollection(spec["id"])
    col = col.filterBounds(region).filterDate(start, end)
    if spec.get("mode"):
        col = col.filter(ee.Filter.eq("instrumentMode", spec["mode"]))
    if spec.get("polarization"):
        col = col.filter(ee.Filter.listContains("transmitterReceiverPolarisation", spec["polarization"]))
    if col.size().getInfo() == 0:
        raise ValueError(f"no {name} scene between {start} and {end}")
    if spec.get("cloud_band"):
        band = spec["cloud_band"]

        def with_clear(image):
            # state_1km bits 0-1: 0 clear, 1 cloudy, 2 mixed, 3 assumed clear.
            cloudy = image.select(band).bitwiseAnd(3).eq(1)
            clear = cloudy.Not().reduceRegion(ee.Reducer.mean(), region, 1000).get(band)
            return image.set("clear", clear)

        col = col.map(with_clear).sort("clear", False)
    else:
        col = col.sort(spec["cloud"] if spec.get("cloud") else "system:time_start")
    image = col.first().select(spec["bands"])
    if spec.get("scale") is not None:
        image = image.multiply(spec["scale"]).add(spec.get("offset", 0))
    return image


def _image(ee, spec, point, start, end):
    kind = spec["kind"]
    if kind == "image":
        image = ee.Image(spec["id"])
    elif kind == "terrain":
        elevation = ee.Image(spec["id"]).select("elevation")
        image = getattr(ee.Terrain, spec["terrain"])(elevation)
    elif kind == "collection":
        col = ee.ImageCollection(spec["id"]).filterBounds(point).select(spec["band"])
        if spec.get("dated"):
            col = col.filterDate(start, end)
        image = getattr(col, spec["aggregate"])()
    else:
        raise ValueError(f"unknown kind {kind}")
    factor = spec.get("scale_factor")
    if factor is not None:
        image = image.multiply(factor)
    return image
