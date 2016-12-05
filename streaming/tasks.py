import os
import luigi
import luigi.contrib.hadoop
import urllib
import tempfile
import xml.etree.ElementTree as ET

import jpylyzer.jpylyzer as jpylyzer # Imported from https://github.com/britishlibrary/jpylyzer
import genblit


class ExternalListFile(luigi.ExternalTask):
    input_file = luigi.Parameter()
    """
    Example of a possible external data dump
    To depend on external targets (typically at the top of your dependency graph), you can define
    an ExternalTask like this.
    """

    def output(self):
        """
        Returns the target output for this task.
        In this case, it expects a file to be present in HDFS.
        :return: the target output for this task.
        :rtype: object (:py:class:`luigi.target.Target`)
        """
        return luigi.contrib.hdfs.HdfsTarget(self.input_file)


class GenerateBlit(luigi.contrib.hadoop.JobTask):
    input_file = luigi.Parameter()

    def output(self):
        return luigi.contrib.hdfs.HdfsTarget("data/blit.tsv")

    def requires(self):
        return ExternalListFile(self.input_file)

    def extra_modules(self):
        return ['jpylyzer']

    def mapper(self, line):
        '''
        Each line should be an identifier of a JP2 file, e.g. 'vdc_100022551931.0x000001'

        In the mapper we download, and then jpylyze it, then convert to blit for output.

        :param line:
        :return:
        '''

        # Download to temp file:
        (jp2_fd, jp2_file) = tempfile.mkstemp()
        download_url = \
            "https://github.com/anjackson/blitter/blob/master/jython/src/test/resources/test-data/%s?raw=true" % line
        (tempfilename, headers) = urllib.urlretrieve(download_url, jp2_file)

        # Jpylyser-it:
        jpylyzer_xml = jpylyzer.checkOneFile(jp2_file)

        # Convert to blit xml:
        blit_xml = genblit.to_blit(jpylyzer_xml)

        # Map to a string, and strip out newlines:
        xml_out = ET.tostring(blit_xml, 'UTF-8', 'xml')
        xml_out = xml_out.replace('\n','')

        print(xml_out)

        # Delete the temp file:
        os.remove(jp2_file)

        # And return:
        yield line, xml_out

    def reducer(self, key, values):
        # Pass-through reducer:
        for value in values:
            yield key, value
        # An actual reducer:
        #yield key, sum(values)


if __name__ == '__main__':
    luigi.run(['GenerateBlit', '--input-file', 'test-input.txt', '--local-scheduler'])