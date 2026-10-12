import sys

# An absolute import, so this file also works as the entry script of the stand-alone app
# (install/edge.spec), where it runs as a plain script and not as part of the edge package.
from edge.cli import main

sys.exit(main())
