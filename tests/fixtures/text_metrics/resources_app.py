from text_metrics import metrics
from text_metrics.resources import stopword_text

print(metrics("A😀 text"))
print(stopword_text(), end="")
