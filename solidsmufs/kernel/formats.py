"""The file types the viewer opens, by extension. Kept apart from the worker so the window process can
check extensions without loading numpy and the geometry code."""

CAD_FORMATS = {".step": "STEP", ".stp": "STEP", ".p21": "STEP", ".igs": "IGES", ".iges": "IGES",
               ".brep": "BREP", ".brp": "BREP"}
PARASOLID_FORMATS = {".sldprt": "SolidWorks part", ".x_t": "Parasolid", ".xmt_txt": "Parasolid",
                     ".x_b": "Parasolid", ".xmt_bin": "Parasolid"}
ASSEMBLY_FORMATS = {".sldasm": "SolidWorks assembly"}
MESH_FORMATS = {".stl": "STL", ".obj": "OBJ", ".ply": "PLY", ".off": "OFF", ".3mf": "3MF", ".glb": "glTF", ".gltf": "glTF"}
ALL_FORMATS = {**CAD_FORMATS, **PARASOLID_FORMATS, **ASSEMBLY_FORMATS, **MESH_FORMATS}
