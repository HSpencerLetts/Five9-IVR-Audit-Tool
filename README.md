# 📞 Five9 IVR Variable, Skill & Prompt Extractor

This is a Streamlit-based web tool for parsing and extracting **Call Variables**, **Variables**, **Skills**, and **Prompt Names** from Five9 IVR XML scripts.

> ⚠️ **Not an official Five9 tool.** This project is provided for illustrative and educational purposes only.

---

## 🧠 Features

- Upload a Five9 IVR XML file exported via the Five9 Admin Web Service API
- Automatically extracts:
  - 🔁 Call Variables (`Group.Variable` format)
  - 💡 Local Variables
  - 🎯 Skills used in skillTransfer modules
  - 🔊 Prompts declared in modules
- Supports multiple scripts per file (batch format)
- Clean, user-friendly UI built in Streamlit
- Outputs downloadable CSV files for each category

---

## 🖥️ Live Demo

You can try it live via Streamlit sharing:

👉 [Launch IVR Reader UI](https://hsl-ivr-reader.streamlit.app/)

---

## 📥 How to Export from Five9

Use the [PSFive9Admin PowerShell module](https://github.com/Five9DeveloperProgram/PSFive9Admin) to retrieve your IVR XML data:

```powershell
Connect-Five9AdminWebService -DataCenter EU # or US
Get-Five9IVRScript | ForEach-Object {
    "<IVRScripts><Name>$($_.Name)</Name><XMLDefinition><![CDATA[$($_.XmlDefinition)]]></XMLDefinition></IVRScripts>"
} | Set-Content -Path "$env:USERPROFILE\Downloads\IVR_Scripts.xml"
