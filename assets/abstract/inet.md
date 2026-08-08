Anomaly detection in multivariate dynamic networks is a fundamental
analytical task. While many methods have been proposed for detecting
anomalous edges or vertex attributes in single snapshots, the **transition
behavior** of vertices across time — the pattern by which a vertex switches
roles or communities — remains under-studied.

We introduce **iNet**, a visual analytics system designed to identify and
explain *irregular transitions* in multivariate dynamic networks. iNet
integrates a glyph-based rare-category identifier, an interactive timeline
view, and coordinated topology and attribute panels, enabling analysts to:

1. Detect rare or anomalous transition patterns at the vertex level;
2. Compare transition signatures across communities;
3. Trace the network conditions that triggered each anomaly.

Case studies on social networks, financial transactions, and traffic data
demonstrate that iNet reveals insights that are difficult to obtain with
existing time-series or static-graph anomaly tools.
