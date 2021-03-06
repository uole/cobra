# -*- coding: utf-8 -*-

"""
    cobra
    ~~~~~

    Implements cobra main

    :author:    BlBana <635373043@qq.com>
    :homepage:  https://github.com/wufeifei/cobra
    :license:   MIT, see LICENSE for more details.
    :copyright: Copyright (c) 2017 Feei. All rights reserved
"""
from phply.phplex import lexer  # 词法分析
from phply.phpparse import make_parser  # 语法分析
from phply import phpast as php
from log import logger

with_line = True


def export(items):
    result = []
    if items:
        for item in items:
            if hasattr(item, 'generic'):
                item = item.generic(with_lineno=with_line)
            result.append(item)
    return result


def export_list(params, export_params):
    """
    将params中嵌套的多个列表，导出为一个列表
    :param params:
    :param export_params:
    :return:
    """
    for param in params:
        if isinstance(param, list):
            export_params = export_list(param, export_params)

        else:
            export_params.append(param)

    return export_params


def get_all_params(nodes):  # 用来获取调用函数的参数列表，nodes为参数列表
    params = []
    export_params = []  # 定义空列表，用来给export_list中使用
    for node in nodes:
        if isinstance(node.node, php.Variable):
            params.append(node.node.name)

        if isinstance(node.node, php.BinaryOp):
            params = get_binaryop_params(node.node)
            params = export_list(params, export_params)

        if isinstance(node.node, php.ArrayOffset):
            params = get_node_name(node.node.node)

    return params


def get_binaryop_params(node):  # 当为BinaryOp类型时，分别对left和right进行处理，取出需要的变量
    params = []
    if isinstance(node.left, php.Variable) and isinstance(node.right, php.Variable):  # left, right都为变量直接取值
        params.append(node.left.name)
        params.append(node.right.name)

    elif isinstance(node.left, php.Variable) and not isinstance(node.right, php.Variable):  # right不为变量时
        params.append(node.left.name)
        params = get_binaryop_deep_params(node.right, params)

    elif not isinstance(node.left, php.Variable) and isinstance(node.right, php.Variable):  # left不为变量时
        params.append(node.right.name)
        params = get_binaryop_deep_params(node.left, params)

    return params


def get_binaryop_deep_params(node, params):  # 取出right，left不为变量时，对象结构中的变量
    """
    取出深层的变量名
    :param node: node为上一步中的node.left或者node.right节点
    :param params:
    :return:
    """
    if isinstance(node, php.ArrayOffset):  # node为数组，取出数组变量名
        param = get_node_name(node.node)
        params.append(param)

    if isinstance(node, php.BinaryOp):  # node为BinaryOp，递归取出其中变量
        param = get_binaryop_params(node)
        params.append(param)

    return params


def get_expr_name(node):  # expr为'expr'中的值
    param_lineno = 0
    is_re = False
    if isinstance(node, php.ArrayOffset):  # 当赋值表达式为数组
        param_expr = get_node_name(node.node)  # 返回数组名
        param_lineno = node.node.lineno

    elif isinstance(node, php.Variable):  # 当赋值表达式为变量
        param_expr = node.name  # 返回变量名
        param_lineno = node.lineno

    elif isinstance(node, php.FunctionCall):  # 当赋值表达式为函数
        param_expr = get_all_params(node.params)  # 返回函数参数列表
        param_lineno = node.lineno
        is_re = is_repair(node.name)  # 调用了函数，判断调用的函数是否为修复函数

    else:
        param_expr = node

    return param_expr, param_lineno, is_re


def get_node_name(node):  # node为'node'中的元组
    if isinstance(node, php.Variable):
        return node.name  # 返回此节点中的变量名


def get_functioncall_params(node):  # functioncall为'functioncall'中的字典{'lineno', 'name':函数名, 'params':参数列表}
    all_params = []
    if 'params' in node:
        params = node['params']  # params包含所有参数的一个列表
        for method, value in params:  # param为每一个参数的元组
            if method == 'Parameter':
                param = get_node_name(value['node'])
                all_params.append(param)
    return all_params


def get_assignment_params(node):  # assignment为'Assignment'中的字典{'expr':表达式为赋值来源, 'is_ref', 'lineno', 'node'}
    if 'expr' in node:
        pass


def is_repair(expr):
    """
    判断赋值表达式是否出现过滤函数，如果已经过滤，停止污点回溯，判定漏洞已修复
    :param expr: 赋值表达式
    :return:
    """
    is_re = False  # 是否修复，默认值是未修复
    if expr == 'escapeshellcmd':
        is_re = True
    return is_re


def is_controllable(expr):  # 获取表达式中的变量，看是否在用户可控变量列表中
    """
    判断赋值表达式是否是用户可控的
    :param expr:
    :return:
    """
    controlled_params = [
        '$_GET',
        '$_POST',
        '$_REQUEST',
        '$_COOKIE',
        '$_FILES',
        '$_SERVER',
        '$HTTP_POST_FILES',
        '$HTTP_COOKIE_VARS',
        '$HTTP_REQUEST_VARS',
        '$HTTP_POST_VARS',
        '$HTTP_RAW_POST_DATA',
        '$HTTP_GET_VARS'
    ]
    if expr in controlled_params:
        return True, expr
    return False, None


def parameters_back(param, nodes):  # 用来得到回溯过程中的被赋值的变量是否与敏感函数变量相等,param是当前需要跟踪的污点
    """
    递归回溯敏感函数的赋值流程，param为跟踪的污点，当找到param来源时-->分析复制表达式-->获取新污点；否则递归下一个节点
    :param param:
    :param nodes:
    :return:
    """
    is_co = False
    cp = None
    if len(nodes) != 0:
        node = nodes[len(nodes) - 1]
        if isinstance(node, php.Assignment):  # 回溯的过程中，对出现赋值情况的节点进行跟踪
            param_node = get_node_name(node.node)  # param_node为被赋值的变量
            param_expr, expr_lineno, is_re = get_expr_name(node.expr)  # param_expr为赋值表达式,param_expr为变量或者列表
            if param == param_node and is_re is True:
                return is_co, cp

            if param == param_node and not isinstance(param_expr, list):  # 找到变量的来源，开始继续分析变量的赋值表达式是否可控
                is_co, cp = is_controllable(param_expr)  # 开始判断变量是否可控
                param = param_expr  # 每次找到一个污点的来源时，开始跟踪新污点，覆盖旧污点
                if is_co is True:
                    logger.warning("[USAGE-CONTROLLABLE] {cp} in line {expr_lineno}".format(cp=cp,
                                                                                            expr_lineno=expr_lineno))

            if param == param_node and isinstance(param_expr, list):
                for expr in param_expr:
                    param = expr
                    _is_co, _cp = parameters_back(param, nodes[:-1])  # 分别对函数参数递归，获取其返回值,返回值为每一个参数的检测情况
                    if _is_co is True:  # 当参数可控时，值赋给is_co 和 cp，有一个参数可控，则认定这个函数可能可控
                        is_co = _is_co
                        cp = _cp

        if is_co is False:  # 当is_co为True时找到可控，停止递归
            is_co, cp = parameters_back(param, nodes[:-1])  # 找到可控的输入时，停止递归

    return is_co, cp


def get_function_params(nodes):
    params = []
    for node in nodes:

        if isinstance(node, php.FormalParameter):
            params.append(node.name)

    return params


def anlysis_function(node):
    """
    对用户自定义的函数进行分析-->获取函数入参-->入参用经过赋值流程，进入sink函数-->此自定义函数为危险函数
    :param node:
    :return:
    """
    function_params = get_function_params(node.params)
    print function_params


def analysis_functioncall(node, back_node, vul_function):
    """
    调用FunctionCall-->判断调用Function是否敏感-->get params获取所有参数-->开始递归判断
    :param node:
    :param back_node:
    :param vul_function:
    :return:
    """
    if node.name == vul_function:  # 定位到敏感函数
        params = get_all_params(node.params)  # 开始取敏感函数中的参数列表
        for param in params:
            is_co, cp = parameters_back(param, back_node)
            if is_co is True:
                logger.warning("[line] The parameters '{param}' from function '{function}' are controllable "
                               "in line {line}".format(param=param, function=node.name, line=node.lineno))

            else:
                logger.warning("[line] The function '{function}' --> '{param}' uncontrollable or vulnerability "
                               "is repaired".format(function=node.name, param=param))


def analysis(nodes, vul_function, back_node):
    """
    调用FunctionCall-->analysis_functioncall分析调用函数是否敏感
    :param nodes: 所有节点
    :param vul_function: 要判断的敏感函数名
    :param back_node: 各种语法结构里面的语句
    :return:
    """
    for node in nodes:
        if isinstance(node, php.FunctionCall):  # 函数直接调用，不进行赋值
            analysis_functioncall(node, back_node, vul_function)

        elif isinstance(node, php.Assignment):  # 函数调用在赋值表达式中
            if isinstance(node.expr, php.FunctionCall):
                analysis_functioncall(node.expr, back_node, vul_function)

        elif isinstance(node, php.If):  # 函数调用在if-else语句中时
            if isinstance(node.node, php.Block):  # if语句中的sink点以及变量
                analysis(node.node.nodes, vul_function, back_node)

            if node.else_ is not None:  # else语句中的sink点以及变量
                if isinstance(node.else_.node, php.Block):
                    analysis(node.else_.node.nodes, vul_function, back_node)

            if len(node.elseifs) != 0:  # elseif语句中的sink点以及变量
                for i_node in node.elseifs:
                    if i_node.node is not None:
                        analysis(i_node.node.nodes, vul_function, back_node)

        elif isinstance(node, php.While) or isinstance(node, php.For):  # 函数调用在循环中
            if isinstance(node.node, php.Block):
                analysis(node.node.nodes, vul_function, back_node)

        elif isinstance(node, php.Function):
            anlysis_function(node)
            # analysis(node.nodes, vul_function, back_node)

        back_node.append(node)


def scan(code_content, sensitive_func):
    """
    开始检测函数
    :param code_content: 要检测的文件内容
    :param sensitive_func: 要检测的敏感函数,传入的为函数列表
    :return:
    """
    back_node = []
    parser = make_parser()
    all_nodes = parser.parse(code_content, debug=False, lexer=lexer.clone(), tracking=with_line)
    for func in sensitive_func:  # 循环判断代码中是否存在敏感函数，若存在，递归判断参数是否可控
        analysis(all_nodes, func, back_node)


# code_contents = """<?php
# $e = $_GET['test'];
# $d = $_GET['test'];
# a($e, $d);
# $c = $_POST['test'];
# system($d,$e);
# shell_exec($c);
#
# """

# code_contents = """<?php
# a==1;
# if(a==1){
# $cmd = $_GET['test'];
# $a = shell_exec($cmd);
# }else{
# $cmd1 = $_POST['test'];
# $b = system($cmd1);
# }
# """

code_contents = """
<?php
$url = $_GET['test'];
function a($url) {
    system($url);
}
?>
"""

F_EXECS = [  # 命令执行的敏感函数
    'backticks',
    'exec',
    'expect_popen',
    'passthru',
    'pcntl_exec',
    'popen',
    'proc_open',
    'shell_exec',
    'system',
    'mail',
    'mb_send_mail',
    'w32api_invoke_function',
    'w32api_register_function',
]

scan(code_contents, F_EXECS)
