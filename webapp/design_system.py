"""Quiet, responsive workspace styling shared by every current page."""

WORKSPACE_CSS = """
<style>
:root {
--tf-bg:#080d16;
--tf-bg-elevated:#0e1623;
--tf-panel:#111c2c;

 --tf-panel-2:#142136;
--tf-panel-hover:#1a2c45;
--tf-border:#29374c;

 --tf-border-soft:#1c293b;
--tf-text:#ecf2fc;
--tf-muted:#96a8c0;

 --tf-primary:#6a9cff;
--tf-primary-strong:#a8c7ff;
--tf-green:#43cfa1;

 --tf-red:#ff8399;
--tf-amber:#e6bc70;
--tf-violet:#b4a3e8;
--tf-radius:12px;
}
html,body,[data-testid="stApp"] {
font-family:Inter,system-ui,sans-serif;
color:var(--tf-text);
}
[data-testid="stAppViewContainer"  ],[data-testid="stMain"] {
background:var(--tf-bg);
}
[data-testid="stHeader"] {
background:rgba(8,13,22,.96);
border-bottom:1px solid var(--tf-border-soft);
}
.block-container {
max-width:1340px;
padding:4rem 2.2rem 3rem;
}
[data-testid="stVerticalBlock"] {
gap:1rem;
}
[data-testid="stSidebar"] {
background:#0b121e;
border-right:1px solid var(--tf-border-soft);
}
[data-testid="stSidebar"] [data-testid="stVerticalBlock"] {
gap:.65rem;
}
[data-testid="stSidebarNav"] a {
border-radius:8px;
min-height:42px;
}
[data-testid="stSidebarNav"] a:hover {
background:#142136;
}
[data-testid="stSidebarNav"] a[aria-current="page"] {
background:#192d4d;
color:#b4ceff;
}
[data-testid="stAppDeployButton"  ],.stAppDeployButton {
display:none;
}
.tf-brand {
display:flex;
align-items:center;
gap:.7rem;
padding:.3rem 0 1rem;
}
.tf-brand-mark {
display:grid;
place-items:center;
width:34px;
height:34px;
border-radius:9px;

 background:#1c3963;
color:#b8d1ff;
font-weight:750;
font-size:.8rem;
}
.tf-brand-title {
font-size:.95rem;
letter-spacing:.09em;
font-weight:750;
}
.tf-brand-sub {
font-size:.69rem;
color:var(--tf-muted);
margin-top:3px;
}
.tf-sidebar-status {
font-size:.75rem;
color:var(--tf-muted);
padding:.6rem 0;
}
.tf-status-row {
display:flex;
justify-content:space-between;
gap:1rem;
margin:.35rem 0;
}
.tf-status-value {
color:var(--tf-text);
}
.tf-dot {
display:inline-block;
width:6px;
height:6px;
border-radius:50%;
margin-right:6px;
}
.tf-dot-green {
background:var(--tf-green);
}.tf-dot-amber {
background:var(--tf-amber);
}
.tf-dot-red {
background:var(--tf-red);
}
.tf-sidebar-label {
font-size:.65rem;
letter-spacing:.12em;
text-transform:uppercase;
color:var(--tf-muted);
}
.tf-kicker {
color:var(--tf-primary);
font-size:.65rem;
letter-spacing:.12em;

 text-transform:uppercase;
margin:.15rem 0 .5rem;
}
.tf-title {
font-size:1.85rem;
line-height:1.2;
font-weight:680;
letter-spacing:-.035em;
margin-bottom:.45rem;
}
.tf-subtitle {
font-size:.9rem;
line-height:1.6;
color:var(--tf-muted);
max-width:820px;
margin-bottom:.5rem;
}
.tf-workspace-bar {
display:flex;
align-items:center;
justify-content:space-between;

 gap:1rem;
padding:.2rem 0 .8rem;
margin-bottom:.5rem;
border-bottom:1px solid var(--tf-border-soft);
}
.tf-workspace-wordmark {
font-size:.72rem;
letter-spacing:.13em;
font-weight:700;
}
.tf-workspace-context,.tf-workspace-time {
display:none;
}
.tf-workspace-meta {
font-size:.65rem;
color:var(--tf-muted);
}
.tf-mode-chip {
border:1px solid var(--tf-border);
border-radius:20px;
padding:4px 9px;
}
.tf-signal-legend {
display:flex;
flex-wrap:wrap;
gap:.7rem;
font-size:.68rem;
color:var(--tf-muted);
}
.tf-signal-legend span {
border:0;
padding:0;
}
[data-testid="stMetric"] {
background:var(--tf-bg-elevated);
border:1px solid var(--tf-border-soft);

 border-radius:var(--tf-radius);
padding:1rem 1.1rem;
min-height:0;
box-shadow:none;
}
[data-testid="stMetricLabel"] p {
font-size:.75rem;
color:var(--tf-muted);
}
[data-testid="stMetricValue"] {
font-size:1.55rem;
font-weight:650;
}
[data-testid="stForm"] {
padding:1.15rem;
border:1px solid var(--tf-border-soft);
border-radius:var(--tf-radius);
}
[data-testid="stExpander"] {
border:1px solid var(--tf-border-soft);
border-radius:10px;
background:transparent;
}
[data-testid="stExpander"] summary {
padding:.75rem 1rem;
font-size:.86rem;
}
[data-testid="stTabs"] [role="tablist"] {
gap:1.2rem;
border-bottom:1px solid var(--tf-border-soft);
}
[data-testid="stTabs"] [role="tab"] {
font-size:.85rem;
min-height:43px;
}
[data-testid="stButton"] button,[data-testid="stFormSubmitButton"] button,
[data-testid="stLinkButton"] a,[data-testid="stDownloadButton"] button {
min-height:42px;

 border-radius:8px;
font-size:.85rem;
padding:.5rem .9rem;
box-shadow:none;
}
[data-testid="stButton"] button:disabled,
[data-testid="stFormSubmitButton"] button:disabled {
opacity:.5;
}
[data-testid="stTextInput"] input,[data-testid="stNumberInput"] input {
min-height:41px;
}
[data-testid="stDataFrame"] {
border:1px solid var(--tf-border-soft);
border-radius:10px;
overflow:hidden;
}
[data-testid="stAlert"] {
border-radius:9px;
font-size:.83rem;
}
[data-testid="stCaptionContainer"] {
color:var(--tf-muted);
font-size:.76rem;
line-height:1.6;
}
[data-testid="stMarkdownContainer"] h3 {
font-size:1.05rem;
font-weight:650;
padding-top:.5rem;
}
[data-testid="stMarkdownContainer"] h2 {
font-size:1.2rem;
font-weight:650;
}
.tf-note,.tf-danger-note {
padding:.8rem 1rem;
border-left:3px solid var(--tf-primary);

 background:var(--tf-bg-elevated);
color:var(--tf-muted);
border-radius:7px;
font-size:.85rem;
}
.tf-danger-note {
border-left-color:var(--tf-red);
}
[class*="st-key-tf_"][class*="_controls"  ],
[class*="st-key-tf_"][class*="_results"] {
height:auto;
max-height:none;
overflow:visible;
}
.st-key-paper_kill_activate button,
.st-key-paper_automation_stop button {
border-color:#78414c;
color:#ffb8c5;
}
.st-key-paper_automation_start button {
border-color:#327660;
color:#9fe5cc;
}
.tf-list-row {
display:flex;
align-items:center;
gap:.8rem;
border-bottom:1px solid var(--tf-border-soft);
padding:.9rem 0;
}
.tf-list-icon {
color:var(--tf-primary);
font-size:1.05rem;
}
.tf-empty {
padding:2rem 1.2rem;
border:1px dashed var(--tf-border);
border-radius:12px;
color:var(--tf-muted);
}
[class*="st-key-tf_watchlist_row"] [data-testid="stHorizontalBlock"] {

 display:grid;grid-template-columns:minmax(0,1fr) 44px;align-items:center;}
[class*="st-key-tf_watchlist_row"] [data-testid="stColumn"] {

 width:100%!important;min-width:0!important;}
[class*="st-key-tf_watchlist_row"] [data-testid="stMarkdownContainer"] p {

 margin:0;font-size:.88rem;font-weight:500;}
[class*="st-key-tf_watchlist_row"] button {
padding:.2rem;min-height:36px;}
[class*="st-key-tf_watchlist_row"] hr {
margin:.25rem 0;}
@media (max-width:760px) {

 .block-container {
padding:4rem .85rem 2rem;
}
 .tf-title {
font-size:1.48rem;
}.tf-subtitle {
font-size:.82rem;
line-height:1.5;
}
 .tf-kicker {
font-size:.6rem;
}.tf-workspace-bar {
padding:.1rem 0 .6rem;
}
 [data-testid="stMetric"] {
padding:.75rem;
}
 [data-testid="stMetricValue"] {
font-size:1.2rem;
}
 [data-testid="stHorizontalBlock"]:has(
> [data-testid="stColumn"] [data-testid="stMetric"]) {

   display:grid;
grid-template-columns:repeat(2,minmax(0,1fr));
gap:.65rem;
}
 [data-testid="stHorizontalBlock"]:has(
> [data-testid="stColumn"] [data-testid="stMetric"])
 > [data-testid="stColumn"] {

   width:100%!important;
min-width:0!important;
}
 .st-key-tf_global_toolbar [data-testid="stHorizontalBlock"] {
display:grid;
grid-template-columns:minmax(0,1fr) 110px;
gap:.5rem;
}
 .st-key-tf_global_toolbar [data-testid="stColumn"] {
width:100%!important;
min-width:0!important;
}
 [data-testid="stForm"] {
padding:.8rem;
}
 [data-testid="stTabs"] [role="tablist"] {
gap:.8rem;
overflow-x:auto;
}
}
</style>
"""
