#!/usr/bin/env bash
set -euo pipefail

bundle="build/pages/mobile-arcade/main.dart.js"

if [[ ! -f "$bundle" ]]; then
  echo "missing bundle: $bundle" >&2
  exit 1
fi

# Make web demo links absolute so navigation from nested /examples routes
# does not append another /examples segment.
perl -0pi -e 's#"examples/web/arcade/index\.html"#"/examples/web/arcade/index.html"#g' "$bundle"
perl -0pi -e 's#"examples/arcade/index\.html"#"/examples/arcade/index.html"#g' "$bundle"
perl -0pi -e 's#"examples/developer-ide/index\.html"#"/examples/developer-ide/index.html"#g' "$bundle"
perl -0pi -e 's#"examples/crypto-lab/index\.html"#"/examples/crypto-lab/index.html"#g' "$bundle"
perl -0pi -e 's#"examples/database-dashboard/index\.html"#"/examples/database-dashboard/index.html"#g' "$bundle"
perl -0pi -e 's#"examples/spatial-pulse/index\.html"#"/examples/spatial-pulse/index.html"#g' "$bundle"
perl -0pi -e 's#"examples/mobile-vs-web/index\.html"#"/examples/mobile-vs-web/index.html"#g' "$bundle"

echo "patched: $bundle"
