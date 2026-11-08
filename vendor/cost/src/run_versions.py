"""Train one model per dataset version and record test accuracy next to Q.

Every version is trained from the FILES ON DISK in data/versions/<version>/images/train,
i.e. exactly the artefacts a colleague would receive, not the in-memory injection.

Run:  python src/run_versions.py            # all versions, skip finished ones
      python src/run_versions.py V07 1      # one version, one seed
"""
import json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("NEU_BATCH", "64")
from PIL import Image
from common import make_split, train_one, RESULTS_DIR, PREFIX_TO_IDX, BATCH
from versions import VERSIONS_DIR

OUT_DIR = os.path.join(RESULTS_DIR, "versions")
EPOCHS = 6
CLEAN = {"V00_clean": [0, 1, 2]}
DEFAULT_SEEDS = {"V21": [0, 1], "V22": [0, 1], "V23": [0, 1], "V24": [0, 1], "V25": [0, 1]}


def list_versions():
    vs = [d for d in os.listdir(VERSIONS_DIR) if os.path.isdir(os.path.join(VERSIONS_DIR, d))]
    return sorted(vs)


def load_version_train(root):
    rows = open(os.path.join(root, "labels.csv")).read().strip().split("\n")[1:]
    files, labels = [], {}
    img_dir = os.path.join(root, "images", "train")
    have = {os.path.splitext(x)[0]: os.path.join(img_dir, x) for x in os.listdir(img_dir)}
    for r in rows:
        f, sub, y, _ = r.split(",")
        if sub != "train":
            continue
        files.append(f)
        labels[f] = int(y)
    files.sort()
    imgs = {}
    for f in files:
        imgs[f] = Image.open(have[os.path.splitext(f)[0]]).convert("L")
    return files, labels, imgs


def run_version(vdir, seed):
    root = os.path.join(VERSIONS_DIR, vdir)
    vid = vdir.split("_")[0]
    man = json.load(open(os.path.join(root, "manifest.json")))
    out = os.path.join(OUT_DIR, "run_%s_s%d.json" % (vdir, seed))
    if os.path.exists(out):
        print("SKIP " + out, flush=True)
        return
    sp = make_split(42)
    files, labels, imgs = load_version_train(root)
    print("VERSION %s seed=%d n_train=%d Q=%.4f defects=%s" %
          (vdir, seed, len(files), man["Q"], man["defects"]), flush=True)
    r = train_one(files, sp["val"], images_train=imgs, labels_train=labels, seed=seed,
                  epochs=EPOCHS, tag=vdir, test_files=sp["test"],
                  log_extra={"version": vdir, "defects": man["defects"], "Q": man["Q"]})
    r["version"] = vdir
    r["manifest"] = man
    os.makedirs(OUT_DIR, exist_ok=True)
    json.dump(r, open(out, "w"), indent=1)
    print("RESULT %s seed=%d test_acc=%.4f Q=%.4f" % (vdir, seed, r["test_acc"], man["Q"]), flush=True)
    print("SAVED " + out, flush=True)


def main():
    vs = list_versions()
    only = sys.argv[1] if len(sys.argv) > 1 else None
    seeds_arg = int(sys.argv[2]) if len(sys.argv) > 2 else None
    for vdir in vs:
        vid = vdir.split("_")[0]
        if only and only not in (vdir, vid):
            continue
        if vid in CLEAN:
            continue  # V00 uses the existing 3-seed clean baseline
        seeds = [seeds_arg] if seeds_arg is not None else DEFAULT_SEEDS.get(vid, [0])
        for s in seeds:
            run_version(vdir, s)


if __name__ == "__main__":
    main()
