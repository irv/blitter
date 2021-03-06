import sys
import xml.etree.ElementTree as ET

def xmlstr_to_blit(jpylyzer_xml_out):
    # Re-parse the XML:
    ET.register_namespace("", "http://openpreservation.org/ns/jpylyzer/")
    jpylyzer_xml = ET.fromstring(jpylyzer_xml_out)

    # Convert to blit xml:
    return to_blit(jpylyzer_xml)


def to_blit(jpylyzer_xml):
    '''
    Generates 'blit' xml from jpylyzer output.
    
    ----
    
    B.4 Tile-component division into resolutions and sub-bands
    
    Each image component is wavelet transformed with N_L decomposition levels as explained in Annex F. As a result, the
    component is available at N_L + 1 distinct resolutions, denoted r = 0,1,...,N_L. The lowest resolution, r = 0, is represented by
    the N_L LL band. In general, resolution r is obtained by discarding sub-bands nHH, nHL, nLH for 
    n = 1 through N_L-r and reconstructing the image component from the remaining sub-bands.
    '''
    '''
    Note the number of 'levels' corresponds to the number of times the DWT is applied.
    This means there are levels+1 resolutions, with the lowest corresponding to the reduced original.
    
    Thus, when there are 6 levels, 7  precinct dimensions are found, starting with the smallest (thumbnail), up to the largest.
    
    Hence, the first (zeroth) resolution does not correspond to a dwt_level. The second (r=1) resolution corresponds to the 
    last (N_L - 1) level.
    '''

    ns = {
        'jpy': "http://openpreservation.org/ns/jpylyzer/",
        'tiff': "http://ns.adobe.com/tiff/1.0/"
    }

    prop = jpylyzer_xml.find('jpy:properties', ns)
    
    ET.register_namespace('blit',"http://bl.uk/namespaces/blit")

    root = ET.Element('blit:blimagetech', 
                      { "xmlns:xsi": "http://www.w3.org/2001/XMLSchema-instance", 
                       "xmlns:xsd": "http://www.w3.org/2001/XMLSchema", 
                       "schemaLocation": "http://bl.uk/namespaces/blit ./blit_v02.xsd",
                       "xmlns:blit" : "http://bl.uk/namespaces/blit" } )
    
    image = ET.SubElement(root, "blit:image")
    image.set("offset", "0")
    
    dim = ET.SubElement(image, "blit:dimension")
    
    dimw = ET.SubElement(dim, "blit:width")
    dimw.set("unit", "pixel")
    dimw.text = prop.find('jpy:jp2HeaderBox/jpy:imageHeaderBox/jpy:width', ns).text
    dimh = ET.SubElement(dim, "blit:height")
    dimh.set("unit", "pixel")
    dimh.text = prop.find('jpy:jp2HeaderBox/jpy:imageHeaderBox/jpy:height', ns).text
    
    res = ET.SubElement(image, "blit:resolution")
    resv = ET.SubElement(res, "blit:x")
    resv.set("unit", "ppi")
    resh = ET.SubElement(res, "blit:y")
    resh.set("unit", "ppi")
    # Attempt to get capture resolution, fall back on display resolution
    try:
        resv.text = prop.find('jpy:jp2HeaderBox/jpy:resolutionBox/jpy:captureResolutionBox/jpy:hRescInPixelsPerInch',
                      ns).text
        resh.text = prop.find('jpy:jp2HeaderBox/jpy:resolutionBox/jpy:captureResolutionBox/jpy:vRescInPixelsPerInch',
                      ns).text
    except:
        try:
            resv.text = prop.find('jpy:jp2HeaderBox/jpy:resolutionBox/jpy:displayResolutionBox/jpy:hResdInPixelsPerInch',
                      ns).text
            resh.text = prop.find('jpy:jp2HeaderBox/jpy:resolutionBox/jpy:displayResolutionBox/jpy:vResdInPixelsPerInch',
                      ns).text
        except:
            num, denom = prop.find('.//tiff:XResolution', ns).text.split('/')
            resh.text = str(int(float(num)/float(denom)))
            num, demon = prop.find('.//tiff:YResolution', ns).text.split('/')
            resv.text = str(int(float(num)/float(denom)))

    chan = ET.SubElement(image, "blit:channels")
    chan.text = prop.find('jpy:jp2HeaderBox/jpy:imageHeaderBox/jpy:nC', ns).text

    chan = ET.SubElement(image, "blit:bitsperchannel")
    chan.text = prop.find('jpy:jp2HeaderBox/jpy:imageHeaderBox/jpy:bPCDepth', ns).text

    # Format section:    
    fmt = ET.SubElement(image, "blit:format")
    fmt.set("xsi:type","blit:jpeg2000")
    
    jp2_compression = ET.SubElement(fmt, "blit:jp2_compression")
    if "irreversible" in prop.find('jpy:contiguousCodestreamBox/jpy:cod/jpy:transformation', ns).text:
        jp2_compression.set("type","JPEG2000_Lossy")
    else: 
        jp2_compression.set("type","JPEG2000_Lossless")
    
    jp2_codeblocksize = ET.SubElement(fmt, "blit:jp2_codeblocksize")
    jp2_cbx = ET.SubElement(jp2_codeblocksize,"blit:jp2_cbx")
    jp2_cbx.text = prop.find('jpy:contiguousCodestreamBox/jpy:cod/jpy:codeBlockWidth', ns).text
    jp2_cby = ET.SubElement(jp2_codeblocksize,"blit:jp2_cby")
    jp2_cby.text = prop.find('jpy:contiguousCodestreamBox/jpy:cod/jpy:codeBlockHeight', ns).text
    
    jp2_layers = ET.SubElement(fmt, "blit:jp2_layers")
    jp2_layers.text = prop.find('jpy:contiguousCodestreamBox/jpy:cod/jpy:layers', ns).text
    
    jp2_progressionorder = ET.SubElement(fmt, "blit:jp2_progressionorder")
    jp2_progressionorder.text = prop.find('jpy:contiguousCodestreamBox/jpy:cod/jpy:order', ns).text
        
    jp2_levels = ET.SubElement(fmt, "blit:jp2_levels")
    jp2_levels.text = prop.find('jpy:contiguousCodestreamBox/jpy:cod/jpy:levels', ns).text

    # Tile dimensions, falling back on image size if tile size is larger:
    jp2_tile_dimensions = ET.SubElement(fmt, "blit:jp2_tile_dimensions")
    xsiz = int(prop.find('jpy:contiguousCodestreamBox/jpy:siz/jpy:xsiz', ns).text)
    ysiz = int(prop.find('jpy:contiguousCodestreamBox/jpy:siz/jpy:ysiz', ns).text)
    xTsiz = int(prop.find('jpy:contiguousCodestreamBox/jpy:siz/jpy:xTsiz', ns).text)
    yTsiz = int(prop.find('jpy:contiguousCodestreamBox/jpy:siz/jpy:yTsiz', ns).text)
    if yTsiz > ysiz:
        yTsiz = ysiz
    if xTsiz > xsiz:
        xTsiz = xsiz
    jp2_tile = ET.SubElement(jp2_tile_dimensions, "blit:jp2_tile")
    jp2_tile.set("dwt_level", ",".join(str(x) for x in range(1,int(jp2_levels.text) + 1)))
    jp2_tile_x = ET.SubElement(jp2_tile,"blit:jp2_tile_x")
    jp2_tile_x.text = str(xTsiz)
    jp2_tile_y = ET.SubElement(jp2_tile,"blit:jp2_tile_y")
    jp2_tile_y.text = str(yTsiz)
    
    # Extract the precincts if present
    if prop.find('jpy:contiguousCodestreamBox/jpy:cod/jpy:precincts', ns).text == "yes":
        jp2_precincts = ET.SubElement(fmt, "blit:jp2_precincts")
        Psx = prop.findall('jpy:contiguousCodestreamBox/jpy:cod/jpy:precinctSizeX', ns)
        Psy = prop.findall('jpy:contiguousCodestreamBox/jpy:cod/jpy:precinctSizeY', ns)
        dwt_levels = ""
        currSize  = Psx[6].text
        for l in range(1,len(Psx) + 1): # 1,2,3,4,5,6,7
            i = len(Psx) - l # 6,5,4,3,2,1,0
            # If this is the last one, or differs from the previous one:
            if i == 0 or currSize != Psx[i].text:
                dwt_levels = dwt_levels[1:]
                jp2_precinct = ET.SubElement(jp2_precincts, "blit:jp2_precinct")
                jp2_precinct.set("dwt_level", dwt_levels)
                jp2_precinct_x = ET.SubElement(jp2_precinct, "blit:jp2_precinct_x")
                jp2_precinct_x.text = currSize
                jp2_precinct_y = ET.SubElement(jp2_precinct, "blit:jp2_precinct_y")
                jp2_precinct_y.text = currSize
                # Store the new current size:
                currSize = Psx[i].text
                # Reset the levels:
                dwt_levels = ""
                    
            # Construct the next levels string:
            dwt_levels += ",%i" % l

    return root

    
if __name__ == '__main__':
    xmlstr = open(sys.argv[1],"rb").read()
    print(ET.tostring(xmlstr_to_blit(xmlstr)))

