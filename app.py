import streamlit as st
import xml.etree.ElementTree as ET
import html
import pandas as pd
import re

# Set Streamlit page configuration
st.set_page_config(page_title="Five9 IVR Audit Tool", layout="wide")

# Display a simple disclaimer
st.info("""
**Disclaimer & Terms of Use**

This web tool is provided *as-is*, without warranty or official support from Five9.  
- All file processing is local and no data is stored or transmitted externally.  
- Intended for educational and illustrative use only.  
- Use at your own risk. For production implementations, please consult Five9 TAMs or Professional Services.
""")

# Title and description
st.title("📞 Five9 IVR Audit Tool")
st.markdown("Upload a Five9 IVR XML file to extract **Call Variables**, **Variables**, **Skills**, and **Prompt Names** from all scripts.")

# Upload XML file
uploaded_file = st.file_uploader("Upload your Five9 IVR XML file", type="xml")

if uploaded_file:
    # Read and decode file content
    raw = uploaded_file.read().decode("utf-8")

    # Extract individual <IVRScripts> blocks
    matches = re.findall(r"<IVRScripts>.*?</IVRScripts>", raw, re.DOTALL)

    # Containers for extracted data
    call_var_rows = []
    var_rows = []
    skill_rows = []
    prompt_rows = []
    failed_scripts = []
    parsed_count = 0

    for block in matches:
        try:
            # Parse each <IVRScripts> block
            script = ET.fromstring(block)
        except ET.ParseError as e:
            # Log any parse errors
            failed_scripts.append({"Script Name": "Unknown (outer parse failed)", "Error": str(e)})
            continue

        # Get script name and embedded XMLDefinition
        name = script.findtext("Name", default="").strip()
        xml_def = script.findtext("XMLDefinition", default="")
        if not xml_def:
            continue

        try:
            # Decode & sanitize embedded IVR XML
            decoded = html.unescape(xml_def)
            decoded = re.sub(r'&(?!amp;|lt;|gt;|quot;|apos;)', '&amp;', decoded)
            decoded = decoded.replace("\x00", "")  # Remove null bytes
            ivr_root = ET.fromstring(decoded)
            parsed_count += 1
        except ET.ParseError as e:
            # Handle decoding errors
            failed_scripts.append({"Script Name": name or "Unknown", "Error": str(e)})
            continue

        # Look for <modules> in the IVR structure
        modules = ivr_root.find("modules")
        if modules is not None:
            for mod in modules:
                tag = mod.tag  # e.g. getDigits, input, skillTransfer, etc.
                mod_name = mod.findtext("moduleName", default="")  # Friendly module label

                # --- VARIABLE EXTRACTION ---

                # Search for all <variableName> tags within the module
                for var_elem in mod.findall(".//variableName"):
                    var_name = var_elem.text
                    if not var_name:
                        continue

                    # Structure the result
                    row = {
                        "Script Name": name,
                        "Module Name": mod_name,
                        "Variable Name": var_name,
                        "Source Module": tag
                    }

                    # Identify as call variable if it uses dot notation
                    if "." in var_name:
                        group, var = var_name.split(".", 1)
                        row["Type"] = "Call Variable"
                        row["Group"] = group
                        call_var_rows.append(row)
                    else:
                        row["Type"] = "Variable"
                        row["Group"] = ""
                        var_rows.append(row)

                # --- SKILL EXTRACTION ---

                if tag == "skillTransfer":
                    # Look inside nested structure for external skill names
                    skill_names = mod.findall(".//listOfSkillsEx/extrnalObj/name")
                    for skill in skill_names:
                        if skill.text:
                            skill_rows.append({
                                "Script Name": name,
                                "Skill Name": skill.text.strip(),
                                "Module Name": mod_name
                            })

                # --- PROMPT EXTRACTION ---

                for prompt in mod.findall(".//prompt"):
                    name_tag = prompt.find("name")
                    if name_tag is not None and name_tag.text:
                        prompt_rows.append({
                            "Script Name": name,
                            "Prompt Name": name_tag.text.strip(),
                            "Module Name": mod_name
                        })

    # ---------- UI OUTPUT: RESULTS DISPLAY ----------

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

    # ---------- UI OUTPUT: ERRORS ----------
    if failed_scripts:
        st.subheader(f"⚠️ {len(failed_scripts)} IVR script(s) failed to process")
        fail_df = pd.DataFrame(failed_scripts)
        st.dataframe(fail_df, use_container_width=True)
        st.download_button("Download Failures CSV", fail_df.to_csv(index=False), "ivr_failures.csv")

    # Final summary
    st.success(f"✅ Processed {parsed_count} IVRs. {len(failed_scripts)} failed.")
