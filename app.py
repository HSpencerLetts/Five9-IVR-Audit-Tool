import streamlit as st
import xml.etree.ElementTree as ET
import html
import pandas as pd
import re
import io

st.set_page_config(page_title="Five9 IVR Variable, Skill & Prompt Extractor", layout="wide")
st.title("📞 Five9 IVR Variable, Skill & Prompt Extractor")
st.markdown("Upload a Five9 IVR XML file to extract **Call Variables**, **Variables**, **Skills**, and **Prompt Names** from all scripts.")

uploaded_file = st.file_uploader("Upload your Five9 IVR XML file", type="xml")

if uploaded_file:
    raw = uploaded_file.read().decode("utf-8")
    matches = re.findall(r"<IVRScripts>.*?</IVRScripts>", raw, re.DOTALL)

    call_var_rows = []
    var_rows = []
    skill_rows = []
    prompt_rows = []
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

                # Extract Variables & Call Variables
                def process_variable(var_name, source):
                    if not var_name:
                        return
                    row = {"Script Name": name, "Variable Name": var_name, "Source Module": source}
                    if "." in var_name:
                        group, var = var_name.split(".", 1)
                        row["Type"] = "Call Variable"
                        row["Group"] = group
                        call_var_rows.append(row)
                    else:
                        row["Type"] = "Variable"
                        row["Group"] = ""
                        var_rows.append(row)

                if tag == "setVariable":
                    for expr in mod.findall(".//expressions"):
                        var_name = expr.findtext("variableName", "")
                        process_variable(var_name, tag)

                elif tag in ["getDigits", "input"]:
                    var_name = mod.findtext(".//targetVariableName", "")
                    process_variable(var_name, tag)

                elif tag == "iterator":
                    var_name = mod.findtext(".//variableName", "")
                    process_variable(var_name, tag)

                # Extract Skills
                if tag == "skillTransfer":
                    skill_names = mod.findall(".//listOfSkillsEx/extrnalObj/name")
                    for skill in skill_names:
                        if skill.text:
                            skill_rows.append({"Script Name": name, "Skill Name": skill.text.strip()})

                # Extract Prompts
                for prompt in mod.findall(".//prompt"):
                    name_tag = prompt.find("name")
                    if name_tag is not None and name_tag.text:
                        prompt_rows.append({"Script Name": name, "Prompt Name": name_tag.text.strip()})

    # Display results
    st.subheader("📂 Call Variables")
    if call_var_rows:
        df_call = pd.DataFrame(call_var_rows).drop_duplicates().sort_values(by=["Script Name", "Variable Name"])
        st.dataframe(df_call, use_container_width=True)
        st.download_button("Download Call Variables CSV", df_call.to_csv(index=False), "call_variables.csv")
    else:
        st.info("No Call Variables found.")

    st.subheader("📂 Variables")
    if var_rows:
        df_var = pd.DataFrame(var_rows).drop_duplicates().sort_values(by=["Script Name", "Variable Name"])
        st.dataframe(df_var, use_container_width=True)
        st.download_button("Download Variables CSV", df_var.to_csv(index=False), "variables.csv")
    else:
        st.info("No Variables found.")

    st.subheader("🎯 Skills")
    if skill_rows:
        df_skill = pd.DataFrame(skill_rows).drop_duplicates().sort_values(by=["Script Name", "Skill Name"])
        st.dataframe(df_skill, use_container_width=True)
        st.download_button("Download Skills CSV", df_skill.to_csv(index=False), "skills.csv")
    else:
        st.info("No Skills found.")

    st.subheader("🔊 Prompts")
    if prompt_rows:
        df_prompt = pd.DataFrame(prompt_rows).drop_duplicates().sort_values(by=["Script Name", "Prompt Name"])
        st.dataframe(df_prompt, use_container_width=True)
        st.download_button("Download Prompts CSV", df_prompt.to_csv(index=False), "prompts.csv")
    else:
        st.info("No Prompts found.")

    # Display Failures
    if failed_scripts:
        st.subheader(f"⚠️ {len(failed_scripts)} IVR script(s) failed to process")
        fail_df = pd.DataFrame(failed_scripts)
        st.dataframe(fail_df, use_container_width=True)
        st.download_button("Download Failures CSV", fail_df.to_csv(index=False), "ivr_failures.csv")

    st.success(f"✅ Processed {parsed_count} IVRs. {len(failed_scripts)} failed.")
