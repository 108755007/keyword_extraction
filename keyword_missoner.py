import jieba
import jieba.analyse
import numpy as np
import pandas as pd
import time
import datetime
from basic.decorator import timing
from jieba_based.jieba_utils import Composer_jieba
from db.mysqlhelper import MySqlHelper
from db import DBhelper
from media.Media import Media
from basic.date import get_hour, date2int, get_today, get_yesterday, check_is_UTC0


## main, process one day if assign date, default is today
@timing
def update_missoner_three_tables(date=None,n=5000,weekday,is_UTC0=False):
    if (date == None):
        date_int = date2int(get_today(is_UTC0=is_UTC0))
    else:
        date_int = date2int(date)
    ## set up config (add word, user_dict.txt ...)
    jieba_base = Composer_jieba()
    all_hashtag = jieba_base.set_config() ## add all user dictionary (add_words, google_trend, all_hashtag)
    stopwords = jieba_base.get_stopword_list()
    stopwords_missoner = jieba_base.read_file('./jieba_based/stop_words_missoner.txt')
    ## set up media
    media = Media()
    web_id_all = fetch_missoner_web_id()
    # web_id_all = ['ctnews']
    df_keyword_crossHot_last = fetch_now_crossHot_keywords(date_int)  ## take keyword in missoner_keyword_crossHot
    if df_keyword_crossHot_last.shape[0]==0:
        df_keyword_crossHot_last = fetch_crossHot_keyword(date_int) ## if size is 0, directly fetch from keyword_missoner
    for web_id in web_id_all:
        ## fetch source domain mapping
        source_domain_mapping = fetch_source_domain_mapping(web_id)
        ## fetch user_based popular article
        df_hot = media.fetch_hot_articles(web_id, n, date=date, is_UTC0=is_UTC0)
        if df_hot.size == 0:
            print('no valid data in dione.report_hour')
            continue
        dict_keyword_article = {}
        i = 0
        keyword_dict = {}
        article_dict = {}
        domain_dict = {}
        keyword_domain_dict = {}
        for index, row in df_hot.iterrows():
            # ## process keyword ##
            keywords, keyword_list, is_cut = generate_keyword_list(row, jieba_base, stopwords, stopwords_missoner)
            params = np.array(row[['pageviews', 'landings', 'exits', 'bounce', 'timeOnPage']]).astype('int')
            params_data = np.array(row[['web_id', 'title', 'content']])
            params_all = np.append(params_data, params)
            article_dict = collect_article_pageviews_by_source(article_dict, row, source_domain_mapping, params_all,params)
            ## separate keyword_list to build dictionary ##

            if row['article_id'] not in domain_dict.keys():
                domain_dict[row['article_id']] = {'internal': 0, 'google': 0, 'facebook': 0, 'yahoo': 0, 'likr': 0,
                                                  'xuite': 0, 'yt': 0, 'LINE': 0, 'feed_related': 0,'dcard':0,'ptt':0,'edm':0 ,'other': 0}
            if row['source_domain'] in source_domain_mapping:
                domain_dict[row['article_id']]['internal'] += int(row['pageviews'])
            elif row['source_domain'] in domain_dict[row['article_id']].keys():
                domain_dict[row['article_id']][row['source_domain']] += int(row['pageviews'])
            else:
                domain_dict[row['article_id']]['other'] += int(row['pageviews'])


            for keyword in keyword_list:
                ## keyword and articles mapping, for table, missoner_keyword_article
                dict_keyword_article[i] = {'web_id': web_id, 'article_id': row['article_id'], 'keyword': keyword, 'is_cut': is_cut}
                i += 1
                ## compute pageviews by external and internal sources, for table, missoner_keyword
                keyword_dict = collect_pageviews_by_source(keyword_dict, keyword, row, source_domain_mapping, params, is_cut)
                if keyword not in keyword_domain_dict.keys():
                    keyword_domain_dict[keyword] = {'internal': 0, 'google': 0, 'facebook': 0, 'yahoo': 0, 'likr': 0,
                                                   'xuite': 0, 'yt': 0, 'LINE': 0, 'feed_related': 0,'dcard':0,'ptt':0,'edm':0,'other': 0}
                if row['source_domain'] in source_domain_mapping:
                    keyword_domain_dict[keyword]['internal'] += int(row['pageviews'])
                elif row['source_domain'] in keyword_domain_dict[keyword].keys():
                    keyword_domain_dict[keyword][row['source_domain']] += int(row['pageviews'])
                else:
                    keyword_domain_dict[keyword]['other'] += int(row['pageviews'])


            print(f"index: {index},article_id:{row['article_id']} ,keywords: {keywords}")
        date = date_int
        hour = get_hour(is_UTC0=is_UTC0)

        ## build dict for building DataFrame
        data_save, data_trend = {}, {}
        i = 0
        for key, value in keyword_dict.items():
            data_save[i] = {'web_id': web_id, 'keyword': key, 'pageviews': value[0], 'external_source_count': value[5],
                            'internal_source_count': value[6], 'landings': value[1], 'exits': value[2],
                            'bounce': value[3], 'timeOnPage': value[4], 'is_cut': value[7], 'date': date}
            data_trend[i] = {'web_id': web_id, 'keyword': key, 'pageviews': value[0], 'hour':hour, 'date':date}
            print(f'{data_save[i]}')
            i += 1
        #####
        data_save_article, data_trend_article = {}, {}
        i = 0
        for key, value in article_dict.items():
            data_save_article[i] = {'web_id': web_id,'article_id':key,'title':value[1],'content':value[2],'pageviews': value[3], 'external_source_count': value[8],
                            'internal_source_count': value[9], 'landings': value[4], 'exits': value[5],
                            'bounce': value[6], 'timeOnPage': value[7], 'date': date}
            data_trend_article[i] = {'web_id': web_id, 'article_id': key, 'pageviews': value[3], 'hour':hour, 'date':date}
            print(f'{data_trend_article[i]}')
            i += 1

        ## deal with trend before replace missoner_keyword table
        df_pageviews_last = fetch_now_keywords_by_web_id(web_id, is_UTC0=False)
        df_pageviews_now = pd.DataFrame.from_dict(data_trend, "index")[['keyword', 'pageviews']]
        df_trend = compute_trend_from_df(df_pageviews_last, df_pageviews_now)
        ## article
        df_pageviews_last_article = fetch_now_article_by_web_id(web_id, is_UTC0=False)
        df_pageviews_now_article  = pd.DataFrame.from_dict(data_trend_article, "index")[['article_id', 'pageviews']]
        df_trend_article  = compute_trend_article_from_df(df_pageviews_last_article, df_pageviews_now_article)

        domain_df = get_domain_df(domain_dict,'article_id',web_id,date_int)
        DBhelper.ExecuteUpdatebyChunk(domain_df, db='dione', table='missoner_article_source_domain', chunk_size=100000,
                                      is_ssh=False)
        keyword_domain_df = get_domain_df(keyword_domain_dict, 'keyword',web_id,date_int)
        DBhelper.ExecuteUpdatebyChunk(keyword_domain_df, db='dione', table='missoner_keyword_source_domain', chunk_size=100000,
                                      is_ssh=False)

        ## build DataFrame
        df_keyword = pd.DataFrame.from_dict(data_save, "index")
        ## merge keyword and trend
        df_keyword = pd.concat([df_keyword.set_index('keyword'), df_trend.set_index('keyword')], axis=1).reset_index(level=0)
        ## select enough number of keywords
        pageviews_array = np.array(df_keyword['pageviews']).astype('int')
        mean_pageviews = np.mean(pageviews_array)
        df_keyword = df_keyword.query(f"pageviews > {mean_pageviews}").fillna(0)
        ## save keyword statistics to table: missoner_keyword
        keyword_list_dict = df_keyword.to_dict('records')
        query_keyword = MySqlHelper.generate_update_SQLquery(df_keyword, 'missoner_keyword')
        MySqlHelper('dione', is_ssh=False).ExecuteUpdate(query_keyword, keyword_list_dict)

        # temp = pd.Timestamp((datetime.datetime.utcnow() + datetime.timedelta(hours=8)).strftime('%Y-%m-%d'))
        # weekday = str(temp.dayofweek + 1)

        df_keyword['hour'] = hour
        if int(hour) <= 2:
            df_keyword['pageviews_hour'] = df_keyword['pageviews']
        else:
            df_keyword_last = fetch_last_hour_article(web_id, hour,'keyword','keyword', weekday,date)
            df_keyword = compute_hour_diff(df_keyword_last,df_keyword,'keyword')


        table_name = f"missoner_keyword_hour_{weekday}"
        keyword_list_dict = df_keyword.to_dict('records')
        query_keyword = MySqlHelper.generate_update_SQLquery(df_keyword, table_name)
        MySqlHelper('dione', is_ssh=False).ExecuteUpdate(query_keyword, keyword_list_dict)
        ###article

        df_article = pd.DataFrame.from_dict(data_save_article, "index")
        ## merge keyword and trend
        df_article = pd.concat([df_article.set_index('article_id'), df_trend_article.set_index('article_id')], axis=1).reset_index(level=0)
        ## select enough number of keywords
        pageviews_array_article = np.array(df_article['pageviews']).astype('int')
        mean_pageviews_article = np.mean(pageviews_array_article)
        df_article = df_article.query(f"pageviews > {mean_pageviews_article}").fillna(0)
        ## save keyword statistics to table: missoner_keyword
        article_list_dict = df_article.to_dict('records')
        query_keyword = MySqlHelper.generate_update_SQLquery(df_article, 'missoner_article')
        MySqlHelper('dione', is_ssh=False).ExecuteUpdate(query_keyword, article_list_dict)

        df_article['hour'] = hour
        if int(hour) <= 2:
            df_article['pageviews_hour'] = df_article['pageviews']
        else:
            df_article_last = fetch_last_hour_article(web_id, hour,'article','article_id', weekday,date)
            df_article = compute_hour_diff(df_article_last,df_article,'article_id')
        article_list_dict = df_article.to_dict('records')
        table_name = f"missoner_article_hour_{weekday}"
        query_keyword = MySqlHelper.generate_update_SQLquery(df_article, table_name)
        MySqlHelper('dione', is_ssh=False).ExecuteUpdate(query_keyword, article_list_dict)




        ## save keywords <=> articles mapping, tabel: missoner_keyword_article
        df_keyword_article = pd.DataFrame.from_dict(dict_keyword_article, "index")
        keyword_article_list_dict = df_keyword_article.to_dict('records')
        query_keyword_article = MySqlHelper.generate_update_SQLquery(df_keyword_article, 'missoner_keyword_article')
        MySqlHelper('dione', is_ssh=False).ExecuteUpdate(query_keyword_article, keyword_article_list_dict)

    # ## save cross hot keywords, tabel: missoner_keyword_crossHot (compute after all web_id ran) (without trend)
    ## deal with trend before replace missoner_keyword_crossHot table
    # df_keyword_crossHot_last = fetch_now_crossHot_keywords(date_int) ## take keyword in missoner_keyword_crossHot
    df_keyword_crossHot_now = fetch_crossHot_keyword(date_int) ## only take top100 keywords from missoner_keyword
    df_trend_crossHot = compute_trend_from_df(df_keyword_crossHot_last, df_keyword_crossHot_now)
    ## merge keyword and trend
    df_keyword_crossHot = pd.concat([df_keyword_crossHot_now.set_index('keyword'), df_trend_crossHot.set_index('keyword')], axis=1)
    ## recover column keyword and remove nan
    df_keyword_crossHot = df_keyword_crossHot.reset_index(level=0).dropna()

    query_crossHot = MySqlHelper.generate_update_SQLquery(df_keyword_crossHot, 'missoner_keyword_crossHot')
    keyword_crossHot_list_dict = df_keyword_crossHot.to_dict('records')
    MySqlHelper('dione', is_ssh=False).ExecuteUpdate(query_crossHot, keyword_crossHot_list_dict)

    df_crossHot_keyword_domain = fetch_crossHot_keyword_domain(date_int)
    DBhelper.ExecuteUpdatebyChunk(df_crossHot_keyword_domain, db='dione', table='missoner_keyword_source_domain_crossHot',chunk_size=100000,is_ssh=False)

    return df_keyword, df_keyword_article, df_keyword_crossHot


def update_crossHot_trend_table(df_hot_keyword, hour):
    hot_keyword_list_dict = df_hot_keyword.to_dict('records')
    data_trend = {}
    for i,data in enumerate(hot_keyword_list_dict):
        data_trend[i] = {'web_id':'crossHot', 'keyword':data['keyword'], 'pageviews':data['pageviews'],
                        'date':data['date'], 'hour':hour}
    df_trend = pd.DataFrame.from_dict(data_trend, "index")
    query = MySqlHelper.generate_update_SQLquery(df_trend, 'missoner_keyword_trend')
    trend_list_dict = df_trend.to_dict('records')
    MySqlHelper('dione', is_ssh=False).ExecuteUpdate(query, trend_list_dict)
    return df_trend
def compute_hour_diff(df_article_last,df_article,name):
    diff = df_article[[name, 'pageviews']].set_index(name).astype({'pageviews': 'int32'}) - df_article_last.set_index(name).astype({'pageviews': 'int32'})
    diff = diff.fillna(0).astype(int).reset_index().rename({'pageviews':'pageviews_hour'},axis='columns')
    df_article = pd.merge(df_article, diff, on=name, how='left')
    return df_article
def compute_trend_from_df(df_pageviews_last, df_pageviews_now):
    ## make pageviews to be int32 and math operation by index:keyword
    df_pageviews_last = df_pageviews_last[['keyword', 'pageviews']].set_index('keyword').astype({'pageviews': 'int32'})
    df_pageviews_now = df_pageviews_now[['keyword', 'pageviews']].set_index('keyword').astype({'pageviews': 'int32'})
    df_trend = ((df_pageviews_now - df_pageviews_last)/df_pageviews_now*100).fillna(0).rename(columns = {'pageviews': 'trend'})

    df_trend = pd.concat([df_trend, df_pageviews_last], axis=1).rename(columns = {'pageviews': 'pageviews_last'})
    df_trend['keyword'] = df_trend.index
    return df_trend
def compute_trend_article_from_df(df_pageviews_last, df_pageviews_now):
    ## make pageviews to be int32 and math operation by index:keyword
    df_pageviews_last = df_pageviews_last[['article_id', 'pageviews']].set_index('article_id').astype({'pageviews': 'int32'})
    df_pageviews_now = df_pageviews_now[['article_id', 'pageviews']].set_index('article_id').astype({'pageviews': 'int32'})
    df_trend = ((df_pageviews_now - df_pageviews_last)/df_pageviews_now*100).fillna(0).rename(columns = {'pageviews': 'trend'})

    df_trend = pd.concat([df_trend, df_pageviews_last], axis=1).rename(columns = {'pageviews': 'pageviews_last'})
    df_trend['article_id'] = df_trend.index
    return df_trend
def get_domain_df(domain_dict,_index,web_id,date_int):
    domain_df = pd.DataFrame.from_dict(domain_dict, 'index')
    domain_df[_index] = domain_df.index
    domain_df['web_id'] = web_id
    domain_df['date'] = date_int
    domain_df.reset_index(drop=True, inplace=True)
    pageviews = domain_df.iloc[:, :-3].apply(np.sum, axis=1)
    domain_df['pageviews'] = pageviews
    mean = sum(pageviews) // len(domain_df)
    domain_df = domain_df[domain_df['pageviews'] > mean]
    return domain_df

@timing
def fetch_crossHot_keyword(date_int):
    query = f"""
            SELECT 
                k.keyword,
                k.pageviews,
                k.external_source_count,
                k.internal_source_count,
                COUNT(ka.article_id) as mentionedArticles,
                k.landings,
                k.exits,
                k.bounce,
                k.timeOnPage
            FROM
                (SELECT 
                    keyword,
                    SUM(pageviews) AS pageviews,
                    SUM(external_source_count) AS external_source_count,
                    SUM(internal_source_count) AS internal_source_count,
                    SUM(landings) AS landings,
                    SUM(exits) AS exits,
                    SUM(bounce) AS bounce,
                    SUM(timeOnPage) AS timeOnPage
                FROM
                    missoner_keyword
                WHERE
                    date = {date_int}
                GROUP BY keyword
                ORDER BY pageviews DESC
                LIMIT 500) AS k
                    INNER JOIN
                missoner_keyword_article ka ON k.keyword = ka.keyword
            GROUP BY k.keyword
            """
    print(query)
    data = MySqlHelper('dione').ExecuteSelect(query)
    df_keyword_crossHot = pd.DataFrame(data, columns=['keyword', 'pageviews', 'external_source_count',
                                                 'internal_source_count', 'mentionedArticles',
                                                 'landings', 'exits', 'bounce', 'timeOnPage'])
    df_keyword_crossHot['date'] = [date_int] * df_keyword_crossHot.shape[0]
    return df_keyword_crossHot
def fetch_crossHot_keyword_domain(date_int):
    query = f"""
            SELECT 
                k.keyword,
                k.pageviews,
                k.internal,
                k.google,
                k.facebook,
                k.yahoo,
                k.likr,
                k.xuite,
                k.yt,
                k.LINE,
                k.feed_related,
                k.other,
                COUNT(ka.article_id) as mentionedArticles
            FROM
                (SELECT 
                    keyword,
                    SUM(pageviews) AS pageviews,
                    SUM(internal) AS internal,
                    SUM(google) AS google,
                    SUM(facebook) AS facebook,
                    SUM(yahoo) AS yahoo,
                    SUM(likr) AS likr,
                    SUM(xuite) AS xuite,
                    SUM(yt) AS yt,
                    SUM(LINE) AS LINE,
                    SUM(feed_related) AS feed_related,
                    SUM(other) AS other
                FROM
                    missoner_keyword_source_domain
                WHERE
                    date = {date_int}
                GROUP BY keyword
                ORDER BY pageviews DESC
                LIMIT 500) AS k
                    INNER JOIN
                missoner_keyword_article ka ON k.keyword = ka.keyword
            GROUP BY k.keyword
            """
    print(query)
    data = MySqlHelper('dione').ExecuteSelect(query)
    df_keyword_domain_crossHot = pd.DataFrame(data, columns=['keyword', 'pageviews', 'internal',
                                                 'google', 'facebook',
                                                 'yahoo', 'likr','xuite' ,'yt', 'LINE','feed_related','other','mentionedArticles'])
    df_keyword_domain_crossHot['date'] = [date_int] * df_keyword_domain_crossHot.shape[0]
    return df_keyword_domain_crossHot
## get latest keyword data
@timing
def fetch_now_crossHot_keywords(date_int):
    # date_int = date2int(get_today(is_UTC0=is_UTC0))
    query = f"SELECT keyword, pageviews FROM missoner_keyword_crossHot WHERE date={date_int}"
    data = MySqlHelper('dione').ExecuteSelect(query)
    df = pd.DataFrame(data, columns=['keyword', 'pageviews'])
    return df

def clean_keyword_list(keyword_list, stopwords, stopwords_missoner):
    keyword_list = Composer_jieba().clean_keyword(keyword_list, stopwords)  ## remove stopwords
    keyword_list = Composer_jieba().clean_keyword(keyword_list, stopwords_missoner)  ## remove stopwords
    keyword_list = Composer_jieba().filter_quantifier(keyword_list)  ## remove number+quantifier, ex: 5.1萬
    keyword_list = Composer_jieba().filter_str_list(keyword_list, pattern="[0-9]{2}")  ## remove 2 digit number
    keyword_list = Composer_jieba().filter_str_list(keyword_list, pattern="[0-9.]*")  ## remove floating
    keyword_list = Composer_jieba().filter_str_list(keyword_list, pattern="[a-z]{1,4}|[A-Z]{2}")  ## remove 1-4 lowercase letter and 2 Upper
    keyword_list = [keyword for keyword in keyword_list if keyword != ''] ## remove blank
    return keyword_list


@timing
def test_speed():
    query = f"""
            SELECT 
                h.web_id, l.title, l.content, h.source_domain, h.pageviews, h.landings,
                h.exits, h.bounce, h.timeOnPage, h.date, h.hour
            FROM
                report_hour h
                    INNER JOIN
                article_list l ON h.article_id = l.signature
                    AND h.web_id = 'ctnews'
                    AND h.date = 20211025
                    AND l.web_id = 'ctnews'
            """
    print(query)
    data = MySqlHelper('dione').ExecuteSelect(query)
    return data


@timing
def fetch_missoner_web_id():
    query = "SELECT web_id FROM web_id_table where missoner_keyword_enable=1"
    print(query)
    data = MySqlHelper('dione').ExecuteSelect(query)
    web_id_all = [d[0] for d in data]
    return web_id_all

@timing
def fetch_source_domain_mapping(web_id):
    query = f"SELECT domain FROM source_domain_mapping where web_id='{web_id}'"
    print(query)
    data = MySqlHelper('dione').ExecuteSelect(query)
    source_domain_mapping = [d[0] for d in data]
    return source_domain_mapping

@timing
def fetch_hot_articles(web_id, n=50, date=None, is_UTC0=False): # default get today's popular articles
    # query = f"SELECT web_id, article_id, clickCountOfMonth, update_time FROM article_click_count WHERE web_id='{web_id}' AND clickCountOfMonth != 0 ORDER BY clickCountOfMonth DESC limit {n}"
    # query = f"SELECT subscriber_browse_record.web_id, subscriber_browse_record.uuid, subscriber_browse_record.article_id, article_list.title, article_list.content FROM subscriber_browse_record inner Join article_list on subscriber_browse_record.article_id=article_list.signature"
    if (date == None):
        date_int = date2int(get_today(is_UTC0=is_UTC0))
    else:
        date_int = date2int(date)
    query = f"""
                SELECT 
                    h.web_id, h.article_id, l.title, l.content, l.keywords, h.source_domain, 
                    SUM(h.pageviews) as pageviews, SUM(h.landings) as landings, SUM(h.exits) as exits,
                    SUM(h.bounce) as bounce, SUM(h.timeOnPage) as timeOnPage, h.date
                FROM
                    report_hour h
                        INNER JOIN
                    article_list l ON h.article_id = l.signature
                        AND h.web_id = '{web_id}'
                        AND h.date = '{date_int}'
                        AND l.web_id = '{web_id}'
                GROUP BY h.article_id, source_domain
                ORDER BY pageviews DESC LIMIT {n}
            """
    print(query)
    data = MySqlHelper('dione').ExecuteSelect(query)
    columns = ['web_id', 'article_id', 'title', 'content', 'keywords', 'source_domain', 'pageviews', 'landings', 'exits', 'bounce', 'timeOnPage', 'date']
    df_hot = pd.DataFrame(data=data, columns=columns)
    return df_hot


## get latest keyword data
@timing
def fetch_now_keywords_by_web_id(web_id, is_UTC0=False):
    date_int = date2int(get_today(is_UTC0=is_UTC0))
    query = f"SELECT keyword, pageviews FROM missoner_keyword WHERE date={date_int} and web_id='{web_id}'"
    data = MySqlHelper('dione').ExecuteSelect(query)
    df = pd.DataFrame(data, columns=['keyword', 'pageviews'])
    return df

def fetch_now_article_by_web_id(web_id, is_UTC0=False):
    date_int = date2int(get_today(is_UTC0=is_UTC0))
    query = f"SELECT article_id, pageviews FROM missoner_article WHERE date={date_int} and web_id='{web_id}'"
    data = MySqlHelper('dione').ExecuteSelect(query)
    df = pd.DataFrame(data, columns=['article_id', 'pageviews'])
    return df

def fetch_last_hour_article(web_id,hour,aok,col,week,date):
    hour =hour - 1
    query = f"SELECT {col}, pageviews FROM missoner_{aok}_hour_{week} WHERE hour='{hour}' and web_id='{web_id}' and date='{date}'"
    data = MySqlHelper('dione').ExecuteSelect(query)
    df = pd.DataFrame(data, columns=[col, 'pageviews'])
    return df

## cut keyword list if keywords is empty
def generate_keyword_list(row, jieba_base, stopwords, stopwords_missoner):
    ## process keyword ##
    keywords = row['keywords']
    news = row['title'] + ' ' + row['content']
    news_clean = jieba_base.filter_str(news, pattern="https:\/\/([0-9a-zA-Z.\/]*)")  ## pattern for https
    news_clean = jieba_base.filter_symbol(news_clean)
    if (keywords == '') | (keywords == '_'):
        keyword_list = jieba.analyse.extract_tags(news_clean, topK=8)
        keyword_list = clean_keyword_list(keyword_list, stopwords, stopwords_missoner)
        keywords = ','.join(keyword_list)  ## add keywords
        is_cut = 1
    else:
        keyword_list = [k.strip() for k in keywords.split(',')]
        keyword_list = clean_keyword_list(keyword_list, stopwords, stopwords_missoner)
        is_cut = 0
    return keywords, keyword_list, is_cut

## compute pageviews by external and internal sources
def collect_pageviews_by_source(keyword_dict, keyword, row, source_domain_mapping, params, is_cut):
    ## save each keyword from a article ##
    if keyword not in keyword_dict.keys():
        ## process internal and external source loop and save to popular keyword dict
        if row['source_domain'] in source_domain_mapping:  # internal case
            keyword_dict[keyword] = np.append(params, [0, row['pageviews'], is_cut])
        else:  # external case
            keyword_dict[keyword] = np.append(params, [row['pageviews'], 0, is_cut])
    else:
        ## process internal and external source loop and add to popular keyword dict
        if row['source_domain'] in source_domain_mapping:  # internal case
            ## add to internal source count
            keyword_dict[keyword][:-1] += np.append(params, [0, row['pageviews']])
        else:  # external case
            ## add to external source count
            keyword_dict[keyword][:-1] += np.append(params, [row['pageviews'], 0])
    return keyword_dict
def collect_article_pageviews_by_source(article_dict,row,source_domain_mapping,params_all,params):
    ## save each keyword from a article ##
    if row['article_id'] not in article_dict.keys():
        ## process internal and external source loop and save to popular keyword dict
        if row['source_domain'] in source_domain_mapping:  # internal case
            article_dict[row['article_id']] = np.append(params_all, [0, row['pageviews']])
        else:  # external case
            article_dict[row['article_id']] = np.append(params_all, [row['pageviews'],0])
    else:
        ## process internal and external source loop and add to popular keyword dict
        if row['source_domain'] in source_domain_mapping:  # internal case
            ## add to internal source count
            article_dict[row['article_id']][3:]+= np.append(params, [0, row['pageviews']])
        else:  # external case
            ## add to external source count
            article_dict[row['article_id']][3:] += np.append(params, [row['pageviews'], 0])
    return article_dict


## analyze data yesterday, insert two tables, missoner_keyword and missoner_keyword_article
if __name__ == '__main__':
    t_start = time.time()
    date = None
    # date = '2021-12-05' ## None: assign today
    is_UTC0 = check_is_UTC0()
    hour_now = get_hour(is_UTC0=is_UTC0)
    temp = pd.Timestamp((datetime.datetime.utcnow() + datetime.timedelta(hours=8)).strftime('%Y-%m-%d'))
    weekday = str(temp.dayofweek + 1)
    if (hour_now == 0):
        ## routine
        # update four tables, missoner_keyword, missoner_keyword_article, missoner_keyword_crossHot, missoner_keyword_trend
        table_name = f"missoner_keyword_hour_{weekday}"
        query = f"TRUNCATE TABLE {table_name}"
        DBhelper('dione').ExecuteSelect(query)

        table_name = f"missoner_article_hour_{weekday}"
        query = f"TRUNCATE TABLE {table_name}"
        DBhelper('dione').ExecuteSelect(query)
        # update four tables, missoner_keyword, missoner_keyword_article, missoner_keyword_crossHot, missoner_keyword_trend

    df_keyword, df_keyword_article, df_keyword_crossHot = update_missoner_three_tables(date=date, n=5000,weekday=weekday,is_UTC0=is_UTC0)

    print(f'routine to update every hour, hour: {hour_now}')

    t_end = time.time()
    t_spent = t_end - t_start
    print(f'finish all routine spent: {t_spent}s')
