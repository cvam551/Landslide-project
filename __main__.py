import argparse
import json

from landslide.earth import IMAGES, SOURCES, dump_images, sample


def main(argv=None):
    parser = argparse.ArgumentParser(description="Sample Earth Engine sources at one point.")
    parser.add_argument("lon", type=float, nargs="?")
    parser.add_argument("lat", type=float, nargs="?")
    parser.add_argument("--sources", help="comma-separated catalog names; default is all")
    parser.add_argument("--start", help="YYYY-MM-DD; required for precipitation and ndvi")
    parser.add_argument("--end", help="YYYY-MM-DD")
    parser.add_argument("--project", help="Cloud project id; defaults to EE_PROJECT")
    parser.add_argument("--list", action="store_true", help="print source and image names")
    parser.add_argument("--auth", action="store_true", help="run ee.Authenticate() and exit")
    parser.add_argument("--dump", metavar="FOLDER", help="save sentinel2, sentinel1, landsat, and modis pngs here")
    parser.add_argument("--images", help="comma-separated satellite names; default is all of them")
    args = parser.parse_args(argv)
    if args.auth:
        import ee

        ee.Authenticate()
        return 0
    if args.list:
        for name, spec in SOURCES.items():
            print(f"{name}\t{spec['id']}")
        for name, spec in IMAGES.items():
            dataset = spec.get("id") or ", ".join(spec["ids"])
            print(f"{name}\t{dataset}")
        return 0
    if args.lon is None or args.lat is None:
        parser.error("lon and lat are required")
    if args.dump:
        for path in dump_images(args.lon, args.lat, args.dump, args.start, args.end, args.images, args.project):
            print(path)
    if args.sources is not None or not args.dump:
        picked = sample(args.lon, args.lat, args.sources, args.start, args.end, args.project)
        print(json.dumps(picked))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
