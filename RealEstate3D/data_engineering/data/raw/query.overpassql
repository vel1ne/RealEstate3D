[out:json][timeout:180];
way["highway"~"^(motorway|motorway_link|trunk|trunk_link|primary|primary_link|secondary|secondary_link|tertiary|tertiary_link|unclassified|residential|living_street|service|track|construction|proposed)$"](51.35,45.70,51.82,46.35)->.roads;
(.roads;node["barrier"](51.35,45.70,51.82,46.35);node["maxheight"](51.35,45.70,51.82,46.35);node["maxweight"](51.35,45.70,51.82,46.35);rel(bw.roads)["type"="restriction"];);
out meta geom;
