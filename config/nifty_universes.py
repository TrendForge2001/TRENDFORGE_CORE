"""Public NSE constituent filenames and membership sanity limits."""

# name, official CSV filename, nominal company count, minimum/maximum securities
ADDITIONAL_NIFTY_UNIVERSES = (
    ("NIFTY LARGEMIDCAP 250", "ind_niftylargemidcap250list.csv", 250, 250, 270),
    ("NIFTY MIDCAP 150", "ind_niftymidcap150list.csv", 150, 150, 165),
    ("NIFTY MIDCAP SELECT", "ind_niftymidcapselect_list.csv", 25, 25, 30),
    ("NIFTY SMALLCAP 250", "ind_niftysmallcap250list.csv", 250, 250, 270),
    ("NIFTY MICROCAP 250", "ind_niftymicrocap250_list.csv", 250, 250, 270),
    ("NIFTY BANK", "ind_niftybanklist.csv", 12, 10, 30),
    ("NIFTY FINANCIAL SERVICES", "ind_niftyfinancelist.csv", 20, 15, 30),
    ("NIFTY IT", "ind_niftyitlist.csv", 10, 10, 25),
    ("NIFTY AUTO", "ind_niftyautolist.csv", 15, 10, 30),
    ("NIFTY FMCG", "ind_niftyfmcglist.csv", 15, 10, 30),
    ("NIFTY PHARMA", "ind_niftypharmalist.csv", 20, 10, 30),
    ("NIFTY METAL", "ind_niftymetallist.csv", 15, 10, 30),
    ("NIFTY REALTY", "ind_niftyrealtylist.csv", 10, 10, 25),
)

NIFTY_UNIVERSES = (
    "NIFTY 50",
    "NIFTY 100",
    "NIFTY 200",
    "NIFTY 500",
    *(row[0] for row in ADDITIONAL_NIFTY_UNIVERSES),
)
