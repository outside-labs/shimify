import json
import sys

from text_metrics import metrics

print(json.dumps(metrics(sys.argv[1])))
