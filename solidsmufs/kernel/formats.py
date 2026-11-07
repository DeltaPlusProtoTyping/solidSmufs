"""The file types the viewer opens, by extension. Kept apart from the worker so the window process can
check extensions without loading numpy and the geometry code."""

# what a PDF that won't open says, so the window can ask for the password rather than report an error
PASSWORD_NEEDED = "This PDF needs a password."
PASSWORD_WRONG = "That password doesn't open this PDF."

CAD_FORMATS = {".step": "STEP", ".stp": "STEP", ".p21": "STEP", ".igs": "IGES", ".iges": "IGES",
               ".brep": "BREP", ".brp": "BREP"}
PARASOLID_FORMATS = {".sldprt": "SolidWorks part", ".x_t": "Parasolid", ".xmt_txt": "Parasolid",
                     ".x_b": "Parasolid", ".xmt_bin": "Parasolid"}
ASSEMBLY_FORMATS = {".sldasm": "SolidWorks assembly"}
MESH_FORMATS = {".stl": "STL", ".obj": "OBJ", ".ply": "PLY", ".off": "OFF", ".3mf": "3MF", ".glb": "glTF", ".gltf": "glTF"}
PDF_FORMATS = {".pdf": "PDF"}
PRC_FORMATS = {".prc": "PRC"}  # the model format inside most 3D PDFs, on its own
U3D_FORMATS = {".u3d": "U3D"}  # the older model format of 3D PDFs, on its own
ALL_FORMATS = {**CAD_FORMATS, **PARASOLID_FORMATS, **ASSEMBLY_FORMATS, **MESH_FORMATS, **PDF_FORMATS, **PRC_FORMATS, **U3D_FORMATS}
