import streamlit as st
import xml.etree.ElementTree as ET
import html
import pandas as pd
import re
import io

st.set_page_config(page_title="Five9 IVR Variable & Skill Extractor", layout="wide")
st.title("📞 Five9 IVR Variable & Skill Extractor")
st.markdown("Upload a Five9 IVR XML file and extract **CAV variables** and **skills** from all scripts.")

uploaded_file = st.file_uploader("Upload your Five9 IVR XML file", type="xml")

if uploaded_file:
    raw = uploaded_file.read().decode("utf-8")
    matches = re.findall(r"<IVRScripts>.*?</IVRScripts>", raw, re.DOTALL)

    cav_rows = []
    skill_rows = []
    failed_scripts = []
    parsed_count = 0

    for block in matches:
        try:
            script = ET.fromstring(block)
        except ET.ParseError as e:
            failed_scripts.append({"Script Name": "Unknown (outer parse failed)", "Error": str(e)})
            continue

        name = script.findtext("Name", default="").strip()
        xml_def = script.findtext("XMLDefinition", default="")
        if not xml_def:
            continue

        try:
            decoded = html.unescape(xml_def)
            decoded = re.sub(r'&(?!amp;|lt;|gt;|quot;|apos;)', '&amp;', decoded)
            decoded = decoded.replace("\x00", "")
            ivr_root = ET.fromstring(decoded)
            parsed_count += 1
        except ET.ParseError as e:
            failed_scripts.append({"Script Name": name or "Unknown", "Error": str(e)})
            continue

        modules = ivr_root.find("modules")
        if modules is not None:
            for mod in modules:
                tag = mod.tag

                # Extract CAV variables from setVariable, getDigits, input, iterator
                if tag == "setVariable":
                    for expr in mod.findall(".//expressions"):
                        var_name = expr.findtext("variableName", "")
                        if var_name:
                            cav_rows.append({"Script Name": name, "Variable Name": var_name, "Source Module": tag})

                elif tag in ["getDigits", "input"]:
                    var_name = mod.findtext(".//targetVariableName", "")
                    if var_name:
                        cav_rows.append({"Script Name": name, "Variable Name": var_name, "Source Module": tag})

                elif tag == "iterator":
                    var_name = mod.findtext(".//variableName", "")
                    if var_name:
                        cav_rows.append({"Script Name": name, "Variable Name": var_name, "Source Module": tag})

                # Extract Skills from skillTransfer modules
                if tag == "skillTransfer":
                    skill_names = mod.findall(".//listOfSkillsEx/extrnalObj/name")
                    for skill in skill_names:
                        if skill.text:
                            skill_rows.append({"Script Name": name, "Skill Name": skill.text.strip()})

    # Results section
    st.subheader("📊 CAV Variable Usage")
    if cav_rows:
        cav_df = pd.DataFrame(cav_rows).drop_duplicates().sort_values(by=["Script Name", "Variable Name"])
        st.dataframe(cav_df, use_container_width=True)
        csv_cav = cav_df.to_csv(index=False).encode("utf-8")
        st.download_button("Download CAV Variables CSV", csv_cav, "cav_variables.csv")
    else:
        st.info("No CAV variables found.")

    st.subheader("🎯 Skill Transfer Usage")
    if skill_rows:
        skill_df = pd.DataFrame(skill_rows).drop_duplicates().sort_values(by=["Script Name", "Skill Name"])
        st.dataframe(skill_df, use_container_width=True)
        csv_skill = skill_df.to_csv(index=False).encode("utf-8")
        st.download_button("Download Skills CSV", csv_skill, "ivr_skills.csv")
    else:
        st.info("No skill transfer data found.")

    # Failures
    if failed_scripts:
        st.subheader(f"⚠️ {len(failed_scripts)} IVR script(s) failed to process")
        fail_df = pd.DataFrame(failed_scripts)
        st.dataframe(fail_df, use_container_width=True)
        csv_fail = fail_df.to_csv(index=False).encode("utf-8")
        st.download_button("Download Failures CSV", csv_fail, "ivr_failures.csv")

    st.success(f"✅ Processed {parsed_count} IVRs. {len(failed_scripts)} failed.")
