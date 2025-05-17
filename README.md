# 📞 Five9 IVR Audit Tool v10.2

**A Streamlit-based web tool for parsing and extracting Call Variables, Variables, Skills, and Prompt Names from Five9 IVR XML scripts — now with diagram exports and more**

> ⚠️ *Not an official Five9 tool. Provided *as-is* for illustrative and educational purposes only.*

---

## 🧠 Key Features (v10.2)

* **IVR Parsing & Extraction**

  * Splits single or batch XML containing multiple `<IVRScripts>` blocks
  * Extracts:

    * 🔁 **Call Variables** (`Group.Variable` format)
    * 💡 **Local Variables**
    * 🎯 **Skills** used in `skillTransfer` modules
    * 🔊 **Prompts** declared in modules

* **User-Friendly UI**

  * Clean, modern styling (rounded cards, shadows)
  * **Global search** filter across all tables
  * **Summary Dashboard**: Scripts processed, failures, unique variable counts
  * **Debug Tools**: Drill into per-script data in an expander

* **Data Export**
  
  * ✅ **CSV** downloads for each category
  * ✅ **Excel** (.xlsx) export of all sheets (Call Variables, Variables, Skills, Prompts, Failures)
  * ✅ **SVG** Single/Bulk Export
  * 🚧 **Single Diagram PDF** *(Work in Progress)*
  * 🚧 **Batch ZIP Export** *(Work in Progress)*

* **Robust XML Handling**

  * Cleans invalid tokens and control characters
  * Explicit checks for missing elements to avoid parse errors

---

## 🖥️ Live Demo

You can try it live via Streamlit sharing:

👉 [Launch IVR Reader UI](https://hsltam.com/)

---

## 📥 Exporting IVR XML from Five9

Use the PowerShell `PSFive9Admin` module to download your IVR scripts:

```powershell
Connect-Five9AdminWebService -DataCenter EU  # or US
Get-Five9IVRScript | ForEach-Object {
    "<IVRScripts><Name>$($_.Name)</Name><XMLDefinition><![CDATA[$($_.XmlDefinition)]]></XMLDefinition></IVRScripts>"
} | Set-Content -Path "$env:USERPROFILE\Downloads\IVR_Scripts.xml"
```

---

## 📦 Requirements

```text
streamlit>=1.24.1
pandas>=2.0.0
graphviz>=0.20.1
openpyxl>=3.1.0
lxml>=4.9.0
xmltodict>=0.13.0
```

> **Note**: Graphviz system package must be installed separately (so `dot` is on your PATH).

---

## 🛠️ Changelog

### v10.2

* **On-demand ZIP export** with progress bar and spinner
* **Orthogonal edge labels** via `xlabel` to avoid warnings
* **Strict XML cleaning** (BOM, control characters)
* **Keyword-only** `to_excel` calls to silence pandas 3.0 FutureWarnings
* **Improved UI**: debug expander default open, reorganized generation flow

### v10.1

* Added PDF export for individual diagrams
* Batch ZIP export of all diagrams

### v10.0

* Call-flow diagram rendering with Graphviz in Streamlit
* Modern CSS styling, debug tools, Excel export, and more

---

## ✉️ Feedback

Send feedback or issues to **[harry.spencerletts@five9.com](mailto:harry.spencerletts@five9.com)**.
