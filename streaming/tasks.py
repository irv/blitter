import os
import time
import luigi
import luigi.contrib.hdfs
import luigi.contrib.hadoop
import urllib
import zipfile
import logging
import tempfile
import xml.etree.ElementTree as ET

import jpylyzer.jpylyzer as jpylyzer # Imported from https://github.com/britishlibrary/jpylyzer
import genblit

logger = logging.getLogger('luigi-interface')


class blit(luigi.Config):
    """
    Configuration class for these tasks

    Parameters:
        http_proxy = Proxy to use for HTTP and HTTPS connections
        url_template = String template to construct a URL from an identifier.

    """
    http_proxy = luigi.Parameter()
    url_template = luigi.Parameter()


class ExternalListFile(luigi.ExternalTask):
    """
    This ExternalTask defines the Target at the top of the task chain. i.e. resources that are overall inputs rather
    than generated by the tasks themselves.
    """
    input_file = luigi.Parameter()

    def output(self):
        """
        Returns the target output for this task.
        In this case, it expects a file to be present in HDFS.
        :return: the target output for this task.
        :rtype: object (:py:class:`luigi.target.Target`)
        """
        return luigi.contrib.hdfs.HdfsTarget(self.input_file)


class RunJpylyzer(luigi.contrib.hadoop.JobTask):
    """
    This class takes a list of identifiers for JPEG2000 files, then downloads them, and then runs Jpylyzer on them
    to extract metadata about the file.

    The output is of the form:

        <identifier><tab><jpylyzer-xml-as-string><newline>
        ....

    Parameters:
        input_file: The file (on HDFS) that contains the list of identifiers.
    """
    input_file = luigi.Parameter()

    # Override the default number of reducers (25)
    n_reduce_tasks = 50

    def jobconfs(self):
        '''
        This patched the job configuration to ensure the output gets stored compressed.
        :return:
        '''
        jcs = super(RunJpylyzer, self).jobconfs()
        jcs.append('mapred.output.compress=true')
        jcs.append('mapred.output.compression.codec=org.apache.hadoop.io.compress.GzipCodec')
        return jcs

    def output(self):
        out_name = "%s.jpylyzer.tsv" % self.input_file
        return luigi.contrib.hdfs.HdfsTarget(out_name, format=luigi.contrib.hdfs.PlainDir)

    def requires(self):
        return ExternalListFile(self.input_file)

    def extra_modules(self):
        return [jpylyzer,genblit]

    def extra_files(self):
        return ["luigi.cfg"]

    def mapper(self, line):
        """
        Each line should be an identifier of a JP2 file, e.g. 'vdc_100022551931.0x000001'

        In the mapper we download, and then jpylyze it

        :param line:
        :return:
        """

        # Ignore blank lines:
        if line == '' or line =='ContentFileUID':
            return

        logger.info("Processing line %s " % line)

        out_key = line
        jpylyzer_xml_out = ""
        retries = 0
        succeeded = False
        while not succeeded and retries < 3:
            # Sleep if this is a retry:
            if retries > 0:
                logger.warning("Sleeping for 30 seconds before retrying...")
                time.sleep(30)
            # Download and analyse the JP2.
            try:
                # Construct URL and download:
                id = line.replace("ark:/81055/","")
                download_url = blit().url_template % id
                logger.warning("Downloading: %s " % download_url)
                # Download via proxy, currently hard-coded and in-memory:
                if blit().http_proxy:
                     logger.warning("Using proxy: %s" % blit().http_proxy)
                     proxies = {'http': blit().http_proxy, 'https': blit().http_proxy}
                else:
                    proxies = None

                data = urllib.urlopen(download_url, proxies=proxies).read()

                # Jpylyzer-it, in memory:
                jpylyzer_xml = jpylyzer.checkOneFileData(id, "", len(data), "", data)

                # Map to a string, and strip out newlines:
                jpylyzer_xml_out = ET.tostring(jpylyzer_xml, 'UTF-8', 'xml')
                jpylyzer_xml_out = jpylyzer_xml_out.replace('\n', ' ').replace('\r', '')

                # Register success:
                succeeded = True

            except Exception as e:
                retries += 1
                out_key = "FAIL %i %s" % (retries, line)
                jpylyzer_xml_out = "Error: %s" % e
                logger.warning("Attempt %i failed with %s" % (retries, e))

        # And return:
        yield out_key, jpylyzer_xml_out

    def reducer(self, key, values):
        """
        A pass-through reducer.

        :param key:
        :param values:
        :return:
        """
        for value in values:
            yield key, value
        # An actual reducer:
        #yield key, sum(values)


class GenerateBlit(luigi.contrib.hadoop.JobTask):
    """
    This class takes the output from Jpylyzer and transforms it into 'blit' XML.

    """
    input_file = luigi.Parameter()

    def requires(self):
        return RunJpylyzer(self.input_file)

    def output(self):
        out_name = "%s.blit.tsv" % self.input_file
        return luigi.contrib.hdfs.HdfsTarget(out_name, format=luigi.contrib.hdfs.PlainDir)

    def extra_modules(self):
        return [jpylyzer,genblit]

    def mapper(self, line):
        """
        Each line should be an identifier of a JP2 file, e.g. 'vdc_100022551931.0x000001' followed by a string
        that is the XML output from Jpylyzer.

        In the mapper we re-parse, then convert to blit for output.

        :param line:
        :return:
        """

        # Ignore blank lines:
        if line == '':
            return

        # Ignore upstream failure:
        if line.startswith("FAIL "):
            return

        try:
            # Split the input:
            id, jpylyzer_xml_out = line.strip().split("\t",1)

            # Re-parse the XML:
            ET.register_namespace("", "http://openpreservation.org/ns/jpylyzer/")
            jpylyzer_xml = ET.fromstring(jpylyzer_xml_out)

            # Convert to blit xml:
            blit_xml = genblit.to_blit(jpylyzer_xml)

            # Map to a string, and strip out newlines:
            blit_xml_out = ET.tostring(blit_xml, 'UTF-8', 'xml')
            blit_xml_out = blit_xml_out.replace('\n', ' ').replace('\r', '')

        except Exception as e:
            id = "FAIL with: %s" % e
            blit_xml_out = line

        # And return both forms:
        yield id, blit_xml_out

    def reducer(self, key, values):
        """
        A pass-through reducer.

        :param key:
        :param values:
        :return:
        """

        for value in values:
            yield key, value
        # An actual reducer:
        #yield key, sum(values)


class GenerateBlitZip(luigi.Task):
    """
    ...
    """
    input_file = luigi.Parameter()

    def requires(self):
        return GenerateBlit(self.input_file)

    def output(self):
        basename = os.path.basename(self.input_file)
        zip_name = "%s.blit.zip" % basename
        return luigi.LocalTarget(zip_name)

    def run(self):
        with zipfile.ZipFile(self.output().path, 'w',
                             compression=zipfile.ZIP_DEFLATED, allowZip64=False) as out_file:
            with self.input().open('r') as in_file:
                for line in in_file:
                    ark, xmlstr = line.strip().split("\t",1)
                    # Write each XML string to a file in the ZIP using a filename based on the ARK:
                    ark_id = ark.replace("ark:/81055/","")
                    out_file.writestr("%s.xml" % ark_id, xmlstr)


if __name__ == '__main__':
    #luigi.run(['GenerateBlitZip', '--input-file', 'test-input.txt', '--local-scheduler'])
    #luigi.run(['GenerateBlitZip', '--input-file', '/blit/Google_DArks_test.csv', '--local-scheduler'])
    luigi.run(['GenerateBlitZip', '--input-file', '/blit/chunks/Google_DArks_ex_alto.csv.chunk00', '--local-scheduler'])

